---
status: planned
created: 2026-09-18
updated: 2026-09-18
---

# Widget de acceso a la cámara en el dashboard

## Objetivo

Añadir al dashboard una tarjeta de vídeo en directo de la EZVIZ C6N de casa, accesible desde los mismos dispositivos conectados a Tailscale que ya usan ha-web. Al pulsar «View live», se abre el stream; al detenerlo, se liberan las conexiones. El resto del dashboard debe seguir funcionando aunque la cámara esté apagada.

Este documento planifica la implementación. No se han instalado servicios de vídeo ni modificado el dashboard para mostrar la cámara.

## Base verificada

- Cámara: EZVIZ C6N, IP actual `192.168.1.199`, puerto RTSP 554, ruta `/`.
- Acceso autenticado desde `pihomeblk-1`, confirmado con `ffprobe`.
- Vídeo H.264 1080p y audio AAC mono a 16 kHz.
- Backend FastAPI y frontend React servidos por Nginx en `charo-vps`.
- Conectividad privada Pi ↔ VPS y cliente ↔ VPS mediante Tailscale.
- Credenciales proporcionadas por el usuario: reutilizarlas al configurar el servicio, sin volver a solicitarlas mientras sigan disponibles en la sesión y sin incorporarlas al repositorio.

Evidencias y diagnóstico: [04-camera-viewer-feasibility.md](04-camera-viewer-feasibility.md).

## Experiencia de usuario

Crear una sección **Camera** después de **Activity timelines**, con una tarjeta **Home camera**. Mantener texto en inglés, temas y estilo del dashboard actual.

- Tarjeta 16:9 adaptable al ancho disponible, con ancho máximo razonable en escritorio y ancho completo en móvil.
- Estado inicial «Ready to connect» y botón **View live**. No mostrar «Online» antes de comprobar reproducción.
- Sin autoplay, capturas periódicas ni conexión de vídeo al cargar la página.
- Al pulsar: «Connecting…»; marcar **Live** únicamente después de recibir y reproducir vídeo.
- Controles **Stop**, **Fullscreen** y audio inicialmente silenciado, con opción **Unmute** si el navegador admite la pista. El vídeo debe poder continuar aunque el audio no sea compatible.
- Usar `playsInline` para móvil; ofrecer controles nativos de vídeo cuando ayuden a compatibilidad o accesibilidad.
- Estados distinguibles: pausada, conectando, en directo, conexión perdida, error de acceso y formato no compatible. Los detalles técnicos sensibles quedan en el servidor.
- Si la imagen se congela, retirar el indicador Live y mostrar reconexión/error. No presentar el último fotograma como vídeo actual.
- Al pulsar Stop, cambiar de página o cerrar la pestaña: cancelar conexión, temporizadores y buffers.
- Al ocultarse la pestaña o salir la tarjeta de la vista durante más de 3 segundos: detenerla y mostrar **Resume live** al volver. No reanudar sin interacción del usuario.
- El rango temporal de las gráficas no afecta al vídeo en directo.
- La tarjeta se renderiza independientemente de la carga/error de sensores de `useDashboardData`; no debe quedar dentro de la condición que oculta el resto del dashboard cuando falla la API de sensores.

## Decisiones técnicas

### Pasarela en la Raspberry

Desplegar **go2rtc** como servicio Docker independiente en `pihomeblk-1`, con configuración reproducible desde este repositorio. Usar un proyecto Compose separado para no acoplar su reinicio al servicio zro-pi.

- Configurar un único stream con identificador estable `home_camera`.
- Entrada RTSP/TCP desde la C6N; primera prueba con la ruta `/` que ya funciona.
- Primera implementación con H.264/AAC originales, sin FFmpeg ni recodificación continua.
- No precargar el stream: verificar que la conexión a la cámara se abre al llegar el primer espectador y se libera al salir el último.
- Comprobar si existe un substream menor. Solo usarlo si se valida; el stream principal probado sigue siendo el punto de partida. No asumir rutas o resoluciones.
- Fijar versión de go2rtc y de su reproductor; revisar documentación y licencia de esa versión antes de incorporarlo.
- Servicio no privilegiado, sin Docker socket, con reinicio automático, healthcheck de proceso y logs limitados. Ajustar CPU/memoria tras medir, teniendo en cuenta el uso actual de swap de la Pi.
- La cámara apagada no debe disparar un reinicio continuo de la pasarela ni del stack de sensores.

### Transporte al navegador

Ruta propuesta: `/camera/home/ws` en Nginx, distinta de `/ws` y `/api/notification-rules`.

1. El navegador conecta a su mismo origen: `ws://<dashboard>/camera/home/ws` o `wss://` cuando exista HTTPS.
2. Nginx conecta a go2rtc en la IP Tailscale de la Pi, con soporte Upgrade y timeouts adecuados.
3. La fuente `home_camera` se fija en servidor; descartar parámetros de origen/URL arbitrarios aportados por el navegador.
4. go2rtc entrega MSE/fMP4 por WebSocket. El componente inserta los fragmentos en el reproductor, preferiblemente reutilizando el cliente mantenido por go2rtc de la versión elegida.
5. El tráfico no pasa por FastAPI, MQTT o InfluxDB. FastAPI podrá dar metadatos públicos de la tarjeta si hacen falta, pero no debe retransmitir fotogramas.

El prototipo de transporte debe comprobar qué mensajes envía el cliente y qué operaciones acepta el WebSocket de go2rtc. Exponer exclusivamente reproducción de la fuente fija; si el proxy y la configuración de go2rtc no permiten imponerlo, añadir una pasarela mínima que filtre el protocolo antes de publicar esa ruta. No dar por seguro un proxy genérico a `/api/`.

### Acceso y secretos

- Mantener el acceso del usuario por Tailscale, como el dashboard actual. No abrir puertos públicos del router o VPS.
- En la Pi, limitar el puerto de go2rtc a Tailscale/localhost y restringirlo al VPS y administración mediante reglas de acceso; el binding a Tailscale por sí solo no autoriza únicamente al VPS.
- Proteger el enlace del VPS con el servicio según las capacidades de la versión elegida. Credenciales de pasarela solo en configuración de servidor, no en JavaScript.
- Guardar la URL RTSP autenticada en un fichero secreto local con permisos restringidos, fuera de Git, montado de solo lectura donde sea posible. Las plantillas llevan placeholders.
- No enviar al navegador la URL RTSP, la contraseña, listados de fuentes con credenciales ni errores sin sanear.
- No publicar la interfaz administrativa, edición de configuración, endpoints de publicación o fuentes arbitrarias de go2rtc. Limitar también Origin/Host y conexiones simultáneas para la ruta de reproducción.
- Un usuario autorizado a acceder al dashboard privado podrá ver la cámara; los roles individuales quedan ligados al futuro sistema de autenticación del proyecto.

### Compatibilidad y recuperación

- Objetivo inicial: MSE/fMP4 con H.264, audio AAC opcional. La compatibilidad se confirma reproduciendo en los navegadores del usuario; `ffprobe` por sí solo no la demuestra.
- Plazo inicial de conexión: 10 segundos. Si no hay vídeo, mostrar error y acción Retry.
- Detectar falta de progreso durante aproximadamente 10 segundos y reintentar como máximo tres veces, con esperas de 1, 3 y 5 segundos; después requerir Retry. Ajustar estos umbrales si las mediciones reales lo justifican.
- Cancelar los reintentos al parar u ocultar el widget; impedir que una conexión antigua reemplace a una sesión nueva del reproductor.
- Si un móvil objetivo no reproduce MSE, evaluar HLS como fallback antes de darlo por soportado. No prometer compatibilidad con todos los Safari/iOS sin prueba real.
- WebRTC queda para una entrega posterior si la latencia medida resulta insuficiente. Necesitaría evaluar candidatos y transporte por Tailscale, además de señalización; no basta con añadir otra ruta HTTP.

## Archivos y despliegues previstos

| Área | Cambios previstos |
|---|---|
| `camera-gateway/compose.yml` | Servicio go2rtc para desplegar en la Pi |
| `camera-gateway/go2rtc.yaml.example` y `.env.example` | Plantillas sin secretos; modo de suministro de credenciales validado contra la versión elegida |
| `frontend-react/nginx.conf` | Ruta de reproducción restringida hacia la Pi |
| `frontend-react/src/components/camera-card.tsx` | Tarjeta y controles |
| `frontend-react/src/hooks/use-camera-stream.ts` | Ciclo de vida, errores, cierre y reintentos |
| `frontend-react/src/lib/` o `vendor/` | Adaptador/reproductor versionado y licencia si se incluye código de go2rtc |
| `frontend-react/src/App.tsx` | Sección Camera independiente del estado de sensores |
| `docs/operacion-host.md`, `README.md`, `claude.md` | Configuración, operación, diagnóstico y uso |

La integración debe estar tras una opción de despliegue que permita ocultar/desactivar la tarjeta y su ruta si aún no está preparada la pasarela. No dejar una tarjeta rota en producción durante la instalación de la Pi.

## Fases de ejecución

### 1. Preparación y prueba de transporte

- [x] Confirmar IP, autenticación RTSP y códecs.
- [ ] Registrar configuración actual de la cámara y firmware sin revelar secretos.
- [ ] Preparar las plantillas y seleccionar versión concreta de go2rtc.
- [ ] Desplegar la pasarela aislada en la Pi y validar el enlace de reproducción desde el VPS.
- [ ] Reproducir H.264/AAC en una página mínima de prueba, primero silenciada.
- [ ] Medir arranque, bitrate, CPU, memoria y cierre de stream; comprobar que no aparece recodificación inesperada.

### 2. Proxy y widget

- [ ] Implementar y validar la restricción de fuente/endpoints/mensajes de reproducción.
- [ ] Añadir la ruta Nginx y el adaptador de reproductor.
- [ ] Crear la tarjeta con View live, Stop, Fullscreen y audio opcional.
- [ ] Implementar estados, detección de congelación, reintentos limitados y liberación de recursos.
- [ ] Verificar temas, teclado, etiquetas accesibles y comportamiento móvil.

### 3. Verificación y entrega

- [ ] Probar desde escritorio y móvil fuera de la LAN doméstica, conectados por Tailscale.
- [ ] Abrir dos espectadores y confirmar que comparten la fuente según la capacidad de go2rtc; medir tráfico Pi/VPS.
- [ ] Probar cámara desconectada, Pi inaccesible, interrupción de red y navegación repetida; restaurar conexión sin afectar sensores o Telegram.
- [ ] Comprobar persistencia de configuración tras reinicio normal de pasarela. Coordinar cualquier reinicio de cámara con el usuario.
- [ ] Guardar respaldo de frontend/proxy anteriores, desplegar y documentar cómo desactivar la función.
- [ ] Recomendar reserva DHCP de `.199`; si se decide configurarla, documentar el cambio concreto del router por separado.

## Criterios de aceptación

- Abrir el dashboard no crea una conexión RTSP ni consume vídeo.
- View live muestra imagen real y actual desde Tailscale; Stop cierra esa sesión y el último espectador libera la fuente.
- Audio empieza silenciado y un fallo de audio no impide ver vídeo.
- No hay imagen congelada etiquetada Live ni reintentos infinitos.
- Cerrar, ocultar o desmontar limpia sockets, listeners y buffers; abrir/cerrar diez veces no acumula conexiones.
- Dos espectadores no interfieren entre sí al iniciar o detener vídeo.
- La cámara funciona aunque falle la API de sensores; los sensores y avisos siguen funcionando aunque falle la cámara.
- No hay contraseñas en assets, respuestas públicas, consola o logs revisados; rutas administrativas y fuentes arbitrarias rechazadas.
- Pruebas de escritorio/móvil, tiempos y consumos quedan registrados con sus límites reales; no afirmar compatibilidad universal.

## Pruebas y rollback

Pruebas automatizadas del ciclo de vida y estados con transporte simulado; pruebas de proxy para rutas/argumentos no permitidos; typecheck y build del frontend. Después, pruebas reales de reproducción y fallos con la C6N. No es necesario guardar imágenes o vídeo para validar esta entrega.

Si falla el despliegue, desactivar la función y restaurar frontend/Nginx anteriores. La pasarela debe poder detenerse de forma independiente, conservando configuración local y sin tocar zro-pi, Mosquitto o InfluxDB.

## Fuera de alcance inicial

Grabación, reproducción histórica, detección de movimiento, PTZ, micrófono de retorno, snapshots por Telegram, acceso público y mosaico multicámara. No se cambiará firmware ni se reseteará la cámara para implementar el widget.
