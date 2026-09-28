---
status: in-progress
created: 2026-09-28
updated: 2026-09-28
---

# Quién entra y quién sale: reconocimiento en la puerta de entrada

## Objetivo

Cuando se abre la puerta de entrada, la cámara debe informar de **quién** ha
entrado o salido. La apertura del sensor Zigbee es el disparo; la identidad sale
del reconocimiento facial y la dirección del recorrido que se ve antes, durante y
después de la puerta, con la comprobación del usuario como refuerzo: si después
de cerrar sigue viéndose a alguien, ha entrado; si ya no está, ha salido.

Decisiones del usuario (2026-09-28):

- Las caras se registran **etiquetando capturas reales** desde el dashboard, no
  subiendo fotos: aprenden con la luz, el ángulo y el infrarrojo de la cámara.
- Cada evento va al **dashboard siempre** y a **Telegram con el mismo interruptor
  temporal** que ya tiene la puerta (`1h`…`7d`).
- Las caras recortadas de eventos se guardan **30 días**. Las etiquetadas como
  muestra de una persona se conservan hasta borrar a esa persona.

## Lo que ve la cámara

Captura del 2026-09-28: la C6N está en la cocina mirando al salón y al comedor.
La puerta de la calle queda **justo fuera del borde derecho** del encuadre. Así
que:

- Quien **entra** aparece por la derecha después de abrirse la puerta y se
  adentra en la escena.
- Quien **sale** cruza la escena hacia la derecha **antes** de que se abra la
  puerta y desaparece por ese borde.

La segunda observación obliga a mirar hacia atrás: si se empieza a analizar al
recibir la apertura, se pierde justo la salida. Por eso hay pre-roll.

Stream verificado desde el VPS: H.264 Main 1920×1080, ~12,5 fps, un keyframe
cada 60 frames (~4,8 s), primer dato a 0,56 s del handshake. Decodificar cuesta
~1 ms por frame en el VPS.

## Arquitectura

```text
Zigbee ─ zro-pi ─ MQTT bridge ─ Mosquitto (VPS) ─┬─ backend (Influx, WS, Telegram)
                                                 └─ presence ◄── go2rtc /api/ws (Pi)
presence ─ MQTT haweb/presence/* ─ backend ─ WS "presence" ─ dashboard
dashboard ─ /api/presence/* (nginx) ─ presence
```

- Servicio nuevo `presence` en el Compose del VPS, **aislado del backend**:
  OpenCV y PyAV no entran en la imagen del backend, y un pico de CPU o un OOM del
  análisis no puede tirar la API de sensores ni los avisos. Límite de 1 CPU y
  768 MB.
- Lee el vídeo por el mismo WebSocket MSE que el navegador, directo a la IP
  Tailscale de la Pi (`CAMERA_GATEWAY_HOSTPORT`). **No cambia nada en la Pi**.
- **Pre-roll**: mantiene la conexión abierta y guarda en RAM los paquetes H.264
  **sin decodificar** de los últimos `PRESENCE_PREROLL_SECONDS` más un GOP. Solo
  demultiplexa, así que el coste continuo es casi nulo (~0,25–2 Mbit/s por
  Tailscale). Al abrirse la puerta decodifica desde el keyframe anterior a
  `apertura − pre-roll`. Nada se escribe en disco salvo los recortes de cara.
  Con `PRESENCE_PREROLL_SECONDS=0` vuelve al modo bajo demanda, a costa de no
  ver las salidas.
- Consume la puerta del mismo `/ZRO/env/#` que el backend, con las mismas
  garantías que los avisos: solo transiciones nuevas, no retenidas, con menos
  de 2 minutos de antigüedad y sin duplicados entre topic individual y agregado.
- Publica `haweb/presence/event` y `haweb/presence/changed` (sin retener). El
  backend los intercepta antes del camino genérico: no van a InfluxDB, se
  reenvían por WebSocket como `presence` y, si la regla de avisos de la puerta
  está activa, encolan el texto para Telegram en la misma cola con las mismas
  garantías (frescura, versión de regla y sin reintento ante entrega dudosa).
- API propia bajo `/api/presence/`, servida por nginx con resolución diferida:
  si `presence` no está arrancado, el resto del dashboard sigue igual.
- Interruptor `CAMERA_PRESENCE_ENABLED` (por defecto `false`): apagado, el
  servicio no se conecta a la cámara y la tarjeta no se monta.

## Análisis de un evento

Ventana: `[apertura − pre-roll, cierre + post-roll]`, con tope de
`PRESENCE_MAX_OPEN_SECONDS` si la puerta se queda abierta. Una nueva apertura
durante el post-roll alarga el mismo evento.

Por cada frame analizado (≈4 fps):

1. **NanoDet** (COCO, clase persona) localiza personas.
2. **YuNet** busca caras en la parte alta de cada persona a resolución completa
   (una cara a 4–5 m mide ~25–40 px en 1080p) y en una pasada global a media
   resolución para caras cercanas.
3. **SFace** obtiene el embedding de 128 dimensiones de cada cara.
4. Un seguidor por solape y distancia une las detecciones en trayectorias.

Clasificación de cada trayectoria con la zona de puerta (`PRESENCE_DOOR_ZONE`,
por defecto la franja derecha `0.8,0,1,1` en coordenadas normalizadas):

| Evidencia | Resultado | Confianza |
|---|---|---|
| Ya estaba antes de abrir y sigue después de cerrar | se quedó (no se informa) | alta |
| Aparece en la zona tras abrir, sigue después de cerrar y fuera de la zona | entró | alta |
| Aparece en la zona tras abrir y sigue después de cerrar **o** se adentra | entró | media |
| Estaba antes, acaba en la zona y no está después de cerrar | salió | alta |
| Acaba en la zona, no está después y o estaba antes o empezó fuera | salió | media |
| Solo se ve después de cerrar | entró | baja |
| Se ve alrededor de la apertura y ya no después de cerrar | salió | baja |

La identidad de una trayectoria es la persona con más votos entre sus caras con
coseno ≥ `PRESENCE_MATCH_THRESHOLD` (0,363, umbral publicado para SFace). Las
trayectorias de la misma persona se funden antes de clasificar. Sin nadie a la
vista, el evento queda como «no se vio a nadie».

«Quién está en casa» se deriva del último evento de cada persona, de modo que
corregir una etiqueta corrige también el estado.

## Etiquetado y datos

- Cada trayectoria guarda su mejor cara (tamaño × confianza) como JPEG pequeño
  y su embedding, en SQLite dentro del volumen `presence-data`.
- En la tarjeta **Presence** cada cara desconocida ofrece **Label**: asignarla
  a una persona existente o crear una nueva. La etiqueta añade la muestra a la
  galería y vuelve a identificar las caras sin etiquetar manual que la
  galería ya reconozca.
- **Ignore** descarta una detección que no es una persona o no interesa.
- Borrar una persona borra sus muestras (derecho de supresión).
- Purga diaria: eventos y caras no etiquetadas de más de
  `PRESENCE_RETENTION_DAYS` (30).
- Las imágenes se sirven solo por la API privada, sin caché, y nunca salen por
  Telegram: el aviso es texto.

## Entregas

1. Servicio `presence`: lectura del stream con pre-roll, detector de puerta,
   modelos, seguimiento, clasificación, SQLite, API y publicación MQTT. Pruebas
   de la lógica pura: puerta, seguimiento, clasificación, identidad y almacén.
2. Backend: interceptar `haweb/presence/*`, WebSocket `presence` y mensajes de
   presencia en la cola de Telegram. Pruebas.
3. Frontend: tarjeta **Presence** con quién está en casa, eventos recientes,
   etiquetado y gestión de personas.
4. Compose, nginx, `.env.example` y documentación.
5. Verificación real con el usuario: entradas y salidas de cada persona,
   etiquetado de las primeras capturas, precisión de día y de noche (IR), y
   consumo de CPU y memoria en el VPS.

## Límites conocidos

- A 4–6 m una cara ocupa pocas decenas de píxeles y de noche la imagen es IR en
  gris: la identificación será menos fiable que la dirección. Por eso cada
  resultado lleva confianza y la persona desconocida es un resultado válido.
- La campana extractora tapa la cabeza de quien pasa por el centro de la
  escena (comprobado de noche el 2026-09-28): ahí solo hay cuerpo, sin cara.
  Las caras útiles salen del lado derecho, al entrar, y de quien camina hacia
  la cocina.
- La cámara no ve la puerta: dos personas que salen juntas y otra que entra a la
  vez pueden confundirse. No se intenta resolver en esta entrega.
- Con la cámara en modo privacidad o apagada, el evento se registra como «sin
  vídeo» y el aviso lo dice.
- La conexión permanente cambia lo documentado en el plan 05 («go2rtc solo abre
  el RTSP con un espectador»): ahora hay siempre un espectador interno. La
  cámara admite un único RTSP compartido por go2rtc, así que el directo del
  dashboard no abre otro.

## Estado (2026-09-28)

Entregas 1–4 desplegadas en el VPS con `CAMERA_PRESENCE_ENABLED=true`
(commits `164ed59` y `0effca2`). Verificado en producción: `presence` sano,
conectado a la pasarela con ~20 s de vídeo en memoria, 1,3 % de CPU y 180 MB
en reposo. El resto del stack sigue sano. Un análisis completo sobre el directo, en proceso
aparte y con apertura simulada (sin tocar MQTT ni el histórico), procesó 60
frames en 11 s. De noche, NanoDet veía a una persona de espaldas con confianza
0,47–0,54 y la partía en dos trayectorias; el umbral bajó de 0,4 a 0,35.

Pendiente: la entrega 5, con aperturas reales, etiquetado de las primeras
caras y medición de aciertos de día y de noche.

## Registro legible (2026-09-28, tras el primer día)

Nueve eventos reales dejaron un registro difícil de usar. Solo 8 de 34
trayectorias tenían imagen, y muchas eran trozos de 0,3–1,1 s marcados como
«salió» sin nada que ver. Además, los recortes de cara mostraban media
habitación: al recolocar la cara detectada dentro del recorte de la cabeza
se sumaba el desplazamiento también al ancho y al alto. Los embeddings no se
veían afectados, porque salen de los puntos de referencia.

- Corregidas las coordenadas de cara.
- Cada trayectoria guarda la **persona entera** en su mejor frame (tamaño ×
  confianza, con prioridad a los que tienen cara y penalizando los cortados por
  el borde). Máximo 320 px.
- Una trayectoria sin cara necesita al menos 3 detecciones y 1 s; la migración
  1 del almacén borra los trozos antiguos que no lo cumplían.
- Las caras sin cuerpo alrededor exigen confianza ≥ 0,9 (el espejo daba falsos
  positivos).
- Etiquetar y descartar son acciones sobre la trayectoria: se puede decir quién
  salió aunque vaya de espaldas. Solo si hay cara, esa etiqueta alimenta la
  galería.
- Borrar a una persona borra también las imágenes de cuerpo que tiene
  atribuidas.

## Archivar y borrar (2026-09-29)

«Dismiss» ocultaba la detección y la sacaba del estado y de la galería,
pero conservaba la imagen hasta la purga: no era ni un borrado ni una
confirmación. El usuario propuso separar las dos intenciones:

- **Archive**: la identificación es correcta. Pasa a `manual`, su cara (si
  la hay) entra en la galería, sigue contando para quién está en casa y
  sale del registro. Una persona desconocida se archiva como desconocida.
- **Delete**: detección errónea o que no interesa. Se borran la fila, la
  imagen y la cara, también como muestra de galería.
- Un evento sale del registro cuando se archiva entero (los que no tienen
  a nadie) o cuando todas sus personas están archivadas. `?include_archived=true`
  en `/api/presence/state` los devuelve.
- La migración 2 convierte los descartes antiguos (`identity = 'ignored'`)
  en borrados.

## Criterios de aceptación

- Una salida real con la persona etiquetada produce «X ha salido» en el
  dashboard y, con la regla activa, un único Telegram adicional al de apertura.
- Una entrada real produce «X ha entrado»; una persona sin etiquetar produce
  «Persona desconocida ha entrado» y su cara aparece para etiquetar.
- Abrir para recoger un paquete y quedarse dentro no cambia el estado.
- Retenidos, reinicios del backend o de `presence`, o eventos de más de 2 min no
  generan eventos.
- Caída de la Pi, la cámara o `presence`: sensores, avisos de puerta y directo
  siguen funcionando.
- CPU media de `presence` en reposo < 5 % de un núcleo; memoria < 500 MB.
