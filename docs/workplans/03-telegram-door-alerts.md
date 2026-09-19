---
status: implemented
created: 2026-09-18
updated: 2026-09-18
---

# Avisos temporales de apertura de puerta por Telegram

## Objetivo y alcance

Permitir activar desde la tarjeta de la puerta un periodo de avisos por Telegram. Durante ese periodo, cada nueva apertura genera un aviso; al caducar, el backend los desactiva aunque el navegador esté cerrado. Primera versión: puerta de entrada, un bot y un chat configurados en el servidor. La estructura permitirá incorporar otros sensores y eventos después.

Implementación realizada el 2026-09-18. Las reglas están apagadas por defecto; la prueba con apertura física y entrega real queda pendiente de activación por el usuario. Duraciones acordadas con el usuario: `1h`, `4h`, `8h`, `1d` y `7d`, con `1h` seleccionada por defecto. `1d` equivale a 24 horas y `7d` a 168 horas desde la activación; no son fechas de calendario.

Complejidad moderada: ya existen MQTT, estados normalizados, timestamps y WebSocket. El trabajo principal consiste en distinguir aperturas nuevas de mensajes repetidos o recuperados y gestionar caducidad y entrega con fiabilidad.

## Experiencia en el dashboard

- En la tarjeta de puerta: interruptor `Telegram alerts` y selector `Duration`. Preferir interruptor a slider continuo: la activación es binaria y las duraciones son discretas.
- Al activar: el servidor confirma `enabled_until`; mostrar `Active until 21:30` y tiempo restante. Usar zona horaria del navegador.
- Al desactivar: cancelar la regla y los envíos pendientes que todavía no hayan comenzado. Una petición a Telegram ya en curso puede completarse.
- Cambiar duración durante una sesión requiere una acción explícita `Extend`; nunca prolongar al recargar la página.
- Si la puerta ya está abierta, mostrarlo; los avisos comienzan en la siguiente apertura, sin enviar un aviso retroactivo.
- Mostrar falta de configuración Telegram, fallo al guardar, desconexión de origen y fallo del último envío. Distinguir regla activa de capacidad de recibir eventos.
- Estado compartido entre navegadores, no guardado únicamente en localStorage. Las notificaciones continúan al cerrar la pestaña.
- Mantener los textos de interfaz en inglés, como el dashboard actual.

## Arquitectura propuesta

### Backend y persistencia

Añadir módulos acotados `notification_rules.py` (reglas, detección y cola), `notifications.py` (API y worker) y `telegram.py`, conectados al flujo de lecturas normalizadas. Persistir reglas, posición del último evento procesado y cola de entrega en SQLite bajo un volumen Docker dedicado, por ejemplo `/data/notifications.sqlite3`. InfluxDB sigue conservando el histórico de sensores.

Una regla contiene `sensor_id`, evento `door_open`, `enabled_from`, `enabled_until` y una versión de sesión. El servidor valida sensor de tipo puerta y una duración del conjunto cerrado `1h`, `4h`, `8h`, `1d`, `7d` (3600, 14400, 28800, 86400 y 604800 segundos, respectivamente). Evaluar la caducidad en cada lectura y antes de cada envío; una tarea periódica actualiza también el estado visible. Al reiniciar, recuperar una sesión únicamente hasta su fecha original de vencimiento.

### API y sincronización

- `GET /api/notification-rules`: estado efectivo, disponibilidad de Telegram y resultado del último envío, sin secretos.
- `PUT /api/notification-rules/{sensor_id}`: activar o extender con duración validada. Incluir control de versión y clave de idempotencia para que reintentar una petición no extienda dos veces.
- `DELETE /api/notification-rules/{sensor_id}`: desactivar de forma idempotente.
- WebSocket `notification_rule`: propagar activación, desactivación, caducidad y errores de entrega a todos los navegadores. Volver a consultar al reconectar.

Mantener el acceso privado por Tailscale. Las mutaciones aceptarán JSON, validarán Origin/Host y restringirán CORS a orígenes configurados; no publicar endpoints de operación en Internet sin autenticación/autorización. En esta primera versión los usuarios con acceso de red autorizado comparten el mismo control y chat.

### Detección de aperturas

El normalizador recibe tanto mensajes individuales como inventarios agregados: la misma lectura puede llegar por ambos. Además, la reconexión MQTT reproduce retenidos y el arranque recupera valores desde InfluxDB.

- Crear un único evaluador para lecturas normalizadas, antes de reemplazar el estado anterior.
- Identificar lectura por sensor y timestamp de origen, con estado; rechazar timestamps anteriores e inconsistencias al mismo timestamp. Persistir la marca procesada para deduplicar tras reinicios.
- Avisar únicamente ante `closed → open`, con timestamp posterior a la activación y regla todavía vigente al procesar/enviar.
- Excluir replay retenido e histórico del envío; pueden establecer la línea base sin generar una apertura. Propagar el flag MQTT retain hasta el evaluador.
- Tras arranque/reconexión, una lectura inicial desconocida establece la línea base. No inferir aperturas ocurridas durante una desconexión. Mostrar que puede haber eventos no observados.
- Exigir frescura del evento (propuesta: máximo 2 minutos de retraso y tolerancia de reloj futura acotada). No basta con el estado online del bridge.
- Mensajes repetidos `open` no producen nuevos avisos; un cierre y una apertura nuevos sí. No introducir un cooldown que oculte aperturas legítimas.
- El QoS 1 del bridge permite preservar el retenido, pero no reemplaza la deduplicación por timestamp: las copias posteriores en el agregado pueden llegar como mensajes no retenidos.

### Entrega Telegram

Usar `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`, ya previstos para el vigilante, verificando presencia sin imprimir valores. Un único destino configurado en servidor; el navegador no podrá proporcionar token, chat arbitrario ni texto libre.

Enviar desde un worker con timeouts, fuera del listener MQTT. Mensaje propuesto: `🚪 Puerta de entrada abierta · 19:42:08 (Europe/Madrid)`. Configurar explícitamente la zona horaria del mensaje. La cola guarda evento y sesión de regla con clave única; antes de enviar comprueba que la sesión no fue desactivada, reemplazada ni caducó.

Gestionar 429 con `retry_after` y fallos transitorios con reintentos limitados, sin entregar avisos antiguos tras vencer su ventana de frescura. Errores permanentes de credenciales/destino se muestran sin bucles de reintento. Evitar secretos en logs y mensajes de error.

Telegram no ofrece una clave de idempotencia para sendMessage: un timeout después de aceptar el mensaje deja un resultado ambiguo. Propuesta: registrar `delivery_unknown` y no reintentar automáticamente ese caso para evitar duplicados. Documentar que no se garantiza entrega exactamente una vez.

## Entregas

1. Motor de reglas y eventos con persistencia y pruebas de caducidad/deduplicación, sin envío real.
2. Adaptador Telegram y worker, probados con respuestas simuladas; configuración y volumen en Compose.
3. API de control y eventos WebSocket, más interruptor/duración en la tarjeta de puerta.
4. Verificación en entorno privado: activar, abrir/cerrar, comprobar un aviso por apertura, desactivar y comprobar silencio. Coordinar esta prueba con el usuario antes de enviar mensajes reales.
5. Documentar variables, comportamiento ante desconexión/reinicio y diagnóstico de entrega.

## Pruebas y criterios de aceptación

- Una apertura durante una sesión activa produce un solo trabajo de envío, aun recibida por topic individual y agregado.
- Activar con la puerta abierta, recuperar InfluxDB, reproducir retenidos o recibir mensajes fuera de orden no genera avisos retroactivos.
- Dos aperturas separadas por un cierre generan dos avisos.
- Caducidad y desactivación bloquean trabajos pendientes, también tras reiniciar y con la pestaña cerrada.
- Dos navegadores reflejan la misma regla; reintentos de la API no prolongan accidentalmente la sesión.
- Telegram lento o caído no bloquea ingesta MQTT, histórico ni dashboard.
- Credenciales ausentes, 429, errores permanentes y entregas ambiguas tienen estados visibles y verificables.
- Validar duración/sensor/origen, navegación con teclado, móvil y temas claro/oscuro.

## Fuera de la primera entrega

Editor genérico de reglas, múltiples destinatarios, horarios recurrentes, comandos desde Telegram, avisos de cierre y control de actuadores. No son necesarios para resolver la apertura temporal de puerta.

## Referencias

- [Telegram Bot API: sendMessage](https://core.telegram.org/bots/api#sendmessage).
- [Telegram Bot API: ResponseParameters y retry_after](https://core.telegram.org/bots/api#responseparameters).


## Validación de la implementación (2026-09-18)

- 50 pruebas de backend pasan, incluyendo 19 nuevas de reglas/API/entrega.
- TypeScript y build de producción correctos.
- Navegador con API/WebSocket simulados: cinco duraciones, activación y desactivación, sincronización entre dos pestañas, temas claro/oscuro y móvil sin desbordamiento.
- No se han enviado mensajes reales durante las pruebas automáticas.
- `Extend` conserva el comienzo de la sesión y amplía su vencimiento hasta, como mínimo, la duración elegida desde ahora; nunca acorta una sesión activa.
- El healthcheck comprueba que el worker de notificaciones sigue ejecutándose.

- Desplegado en `charo-vps` el 2026-09-18: backend y Nginx saludables; `/api/health` confirma worker activo y Pi online.
- Navegador real por Tailscale: control habilitado pero apagado, cinco duraciones, WebSocket conectado y sin errores JavaScript.
- API real: origen externo rechazado (403), sensor desconocido rechazado (404). No se activó ninguna regla de producción.
- Respaldo de fuentes: `/opt/projects/ha-web-backups/telegram-20260918/source-before.tgz`; imágenes anteriores etiquetadas `before-telegram-20260918`.
- Aviso preexistente de dependencias: `npm audit` identifica `nanoid <3.3.18`, transitivo de PostCSS/Vite y usado solo durante la compilación. La imagen final sirve assets con Nginx y no incluye esa dependencia. Actualización de herramientas pendiente fuera de esta entrega.
