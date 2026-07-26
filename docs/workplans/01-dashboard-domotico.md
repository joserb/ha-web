---
status: in-progress
created: 2026-07-26
updated: 2026-07-26
---

# Dashboard doméstico: evolución de `ha-web`

**Repositorio:** `ha-web`
**Objetivo:** convertir el prototipo actual en un dashboard doméstico seguro, configurable, observable y accesible desde Tailscale o Internet.

## Contexto

El sistema existente ya resuelve el flujo básico MQTT → FastAPI → InfluxDB → WebSocket → navegador. El despliegue actual lleva semanas estable y conserva una superficie pequeña, por lo que se evolucionará incrementalmente en lugar de reemplazarlo.

El producto final debe mostrar valores actuales, tendencias multicanal e intervalos de apertura de puertas; admitir nuevos sensores sin modificar la aplicación; respetar el tema del dispositivo; y ofrecer acceso público autenticado sin exponer MQTT, InfluxDB ni FastAPI.

## Decisiones de diseño

### Arquitectura

- Mantener Mosquitto, InfluxDB 2, FastAPI, Nginx y el frontend web modular.
- Nginx será el único punto de entrada desde Internet y terminará TLS.
- MQTT, InfluxDB y FastAPI permanecerán en redes privadas de Docker o ligados a localhost/Tailscale.
- Separar lectura de sensores y control de actuadores. El navegador no podrá publicar topics MQTT arbitrarios.
- Incorporar un catálogo de sensores versionado como fuente de nombres, unidades, familias, límites y visualización.
- Considerar el servicio Python `zro-pi` desplegado en `pihomeblk-1` como fuente de verdad del inventario doméstico actual. Home Assistant solo corresponde al histórico anterior. El catálogo servido por el VPS será una proyección del contrato normalizado `/ZRO/env/*`, no un inventario paralelo mantenido manualmente.
- Mantener el broker primario en la Raspberry y replicar hacia el VPS por un bridge MQTT sobre Tailscale, limitado inicialmente a `/ZRO/env/#` en dirección de entrada.

### Rangos temporales globales

El dashboard tendrá un selector global con estos valores exactos:

| Opción | Periodo |
|---|---:|
| `1h` | 1 hora |
| `6h` | 6 horas |
| `12h` | 12 horas |
| `1d` | 1 día |
| `7d` | 7 días |
| `30d` | 30 días |
| `3m` | 3 meses |
| `6m` | 6 meses |
| `1y` | 1 año |
| `forever` | toda la retención disponible |

- El rango seleccionado se aplicará a todas las gráficas de tendencia y timelines.
- La selección se reflejará en la URL y se conservará localmente.
- El backend aceptará únicamente los identificadores anteriores; no recibirá fragmentos Flux arbitrarios.
- El tamaño de ventana de agregación será automático para mantener una cantidad acotada de puntos:
  - `1h`: 1 minuto.
  - `6h`: 5 minutos.
  - `12h`: 10 minutos.
  - `1d`: 15 minutos.
  - `7d`: 1 hora.
  - `30d`: 6 horas.
  - `3m`: 12 horas.
  - `6m`: 1 día.
  - `1y`: 2 días.
  - `forever`: ventana calculada según retención, con límite de puntos.
- La zona horaria de presentación será la del navegador; API y almacenamiento usarán UTC.

### Tendencias multicanal

- Las tendencias se mostrarán en una sección apilada y sincronizada, compartiendo eje temporal.
- Los canales se agruparán por familia: temperaturas, humedades, baterías, calidad del aire, consumos y otras familias configuradas.
- Cada familia y cada canal individual se podrán activar o desactivar.
- La selección de canales se conservará en el navegador.
- Las escalas no mezclarán unidades incompatibles. Se usarán paneles apilados por unidad/familia en vez de superponer magnitudes engañosas.
- Todas las gráficas compartirán cursor, tooltip y zoom temporal cuando la librería elegida lo permita.
- La API ofrecerá consultas por lotes para evitar una petición independiente por sensor.

### Tipos de card

#### `meter`

- Valor actual destacado, unidad, actualización y estado de disponibilidad.
- Escala, límites y umbrales configurables.
- Indicador de tendencia y sparkline opcional.
- Estados normal, aviso, alarma y dato obsoleto accesibles sin depender solo del color.
- Aplicable a temperatura, humedad, CO₂, batería, presión, consumo y otras magnitudes numéricas.

#### `timeline`

- Representar aperturas y cierres como intervalos, incluyendo duración.
- Mostrar estado actual, número de aperturas y tiempo total abierto.
- Resolver aperturas sin cierre, cierres sin apertura previa, duplicados y límites del periodo consultado.
- El backend devolverá intervalos ya normalizados; el frontend no reconstruirá la semántica desde eventos crudos.
- Compartir el rango temporal global con las tendencias.

### Temas

- Modos `system`, `light` y `dark`.
- `system` seguirá `prefers-color-scheme` y reaccionará a cambios en vivo.
- Una selección manual tendrá prioridad y se guardará en `localStorage`.
- Variables CSS semánticas cubrirán página, cards, texto, bordes, gráficas y estados.
- Evitar destellos del tema incorrecto durante la carga.
- Contraste mínimo WCAG AA y estados distinguibles por texto/icono además de color.

### Acceso público

- Requisito previo: dominio o subdominio apuntando a `5.75.145.65`.
- Publicar únicamente TCP 80/443; redirigir HTTP a HTTPS.
- Certificados automáticos de Let's Encrypt.
- Mantener Tailscale como vía administrativa y alternativa privada.
- Autenticación con sesiones seguras, contraseñas con hash fuerte, expiración y rate limiting.
- Roles iniciales: `viewer` y `operator`.
- Recomendar TOTP para cuentas con permiso de operación.
- Cookies `Secure`, `HttpOnly` y `SameSite`; protección CSRF en escrituras.
- CORS y orígenes WebSocket restringidos al dominio configurado.
- CSP, HSTS, límites de petición y auditoría de accesos/acciones.
- Evaluar Authelia/Authentik frente a autenticación integrada antes de implementar. La decisión se documentará mediante ADR.

## Plan de ejecución

### Fase 0 — Salvaguarda y línea base

- [x] Crear backup verificable de InfluxDB y configuraciones persistentes.
- [ ] Documentar restauración y rollback.
- [ ] Registrar versiones, uso de disco y estado inicial de los servicios.
- [ ] Añadir una comprobación automatizada de endpoints existentes.

### Fase 1 — Contratos y seguridad del backend

- [ ] Separar configuración, MQTT, InfluxDB, API y WebSocket.
- [ ] Introducir modelos Pydantic y validación estricta.
- [x] Implementar catálogo versionado de sensores y esquema de validación.
- [x] Importar o sincronizar el inventario real desde la configuración y los mensajes normalizados de `zro-pi` en `pihomeblk-1`.
- [ ] Crear endpoints normalizados de catálogo, valores actuales, tendencias e intervalos.
- [x] Implementar rangos temporales mediante enumeración cerrada y ventanas controladas.
- [ ] Añadir consulta multicanal por lotes.
- [ ] Añadir pruebas unitarias para topics, payloads, rangos e intervalos.
- [x] Evitar operaciones síncronas de InfluxDB dentro del bucle asíncrono.

### Fase 2 — Estado MQTT fiable

- [x] Replicar `/ZRO/env/#` desde `pihomeblk-1` al VPS mediante bridge MQTT sobre Tailscale.
- [ ] Normalizar topics `state`, `availability` y `set`.
- [ ] Usar mensajes retenidos para el valor actual.
- [x] Detectar datos obsoletos mediante `stale_after`.
- [ ] Crear usuarios separados y ACL de mínimo privilegio.
- [x] Recuperar estado desde MQTT retenido o InfluxDB tras reinicios.
- [ ] Rechazar publicación MQTT arbitraria desde WebSocket.

### Fase 3 — Sistema de dashboard y cards

- [x] Consumir el catálogo desde la API.
- [ ] Crear layout y registro común de cards.
- [x] Implementar card `meter`.
- [ ] Implementar card `timeline`.
- [ ] Implementar sección de tendencias apiladas.
- [x] Añadir selector global `1h`–`forever`.
- [ ] Añadir selector de familias y canales.
- [ ] Persistir rango, familias, canales y layout.
- [ ] Adaptar la interfaz a móvil, tableta y escritorio.

### Fase 4 — Tema y accesibilidad

- [ ] Crear tokens CSS para temas claro y oscuro.
- [ ] Añadir selector `system`/`light`/`dark`.
- [ ] Adaptar gráficas y tooltips al tema.
- [ ] Verificar teclado, lectores de pantalla, contraste y movimiento reducido.

### Fase 5 — Acceso autenticado desde Internet

- [ ] Crear ADR de proveedor y modelo de identidad.
- [ ] Configurar dominio, TLS y proxy frontal.
- [ ] Implementar autenticación, sesiones y roles.
- [ ] Añadir rate limiting, protección CSRF y auditoría.
- [ ] Separar endpoints de lectura y operación.
- [ ] Verificar desde una red externa que solo 80/443 sean accesibles.
- [ ] Ejecutar pruebas de autorización y endurecimiento.

### Fase 6 — Operación y conservación de datos

- [ ] Fijar versiones de imágenes y dependencias.
- [ ] Añadir healthchecks, límites y rotación de logs.
- [ ] Definir retención y downsampling de InfluxDB.
- [ ] Automatizar backups cifrados fuera del VPS.
- [ ] Probar una restauración completa.
- [ ] Añadir métricas y alertas de servicios, disco, backups y sensores obsoletos.

## Estrategia de entrega

- Cada fase se dividirá en commits pequeños y reversibles.
- No se migrará el esquema histórico sin backup y prueba de compatibilidad.
- Las rutas existentes se mantendrán durante una transición deprecada.
- El acceso público no se habilitará hasta completar autenticación, autorización y revisión de exposición de puertos.
- Los cambios se desplegarán primero mediante Tailscale y se verificarán con datos reales.

## Criterios de aceptación

- Añadir un sensor requiere configuración, no cambios de frontend.
- Las cards `meter` muestran valor, unidad, antigüedad y disponibilidad.
- Las cards `timeline` muestran intervalos y duraciones correctos.
- El rango global ofrece exactamente `1h`, `6h`, `12h`, `1d`, `7d`, `30d`, `3m`, `6m`, `1y` y `forever`.
- Cambiar el rango actualiza todas las tendencias y timelines.
- Familias y canales se pueden ocultar sin perder la preferencia al recargar.
- Magnitudes incompatibles no comparten una escala engañosa.
- El tema sigue al sistema y admite preferencia manual persistente.
- Reiniciar el stack no elimina los valores actuales visibles.
- El acceso público usa HTTPS y exige credenciales.
- Un `viewer` no puede ejecutar acciones y ningún usuario puede publicar topics arbitrarios.
- MQTT, InfluxDB y FastAPI no son accesibles directamente desde Internet.
- Existe un backup externo y una restauración probada.

## Riesgos y asuntos pendientes

- El rango `forever` depende de la política final de retención y downsampling.
- El dominio y el proveedor de identidad requieren una decisión antes de la fase pública.
- Debe preservarse el histórico capturado desde Home Assistant mientras la ingesta nueva adopta el contrato `/ZRO/env/*` de `zro-pi`.
- La librería actual de gráficas puede no ser suficiente para cursor sincronizado y grandes rangos; se evaluará antes de la fase 3.
- La instancia comparte VPS con otros stacks; cualquier cambio de proxy o firewall debe preservar su funcionamiento.

## Registro de progreso

- 2026-07-26: plan inicial creado a partir de la auditoría del despliegue activo.
- 2026-07-26: ejecución iniciada con el contrato de rangos temporales y el selector global del dashboard.
- 2026-07-26: backup online creado y primera entrega desplegada; los diez rangos, la compatibilidad con `hours` y el rechazo de rangos inválidos quedan verificados en el VPS.
- 2026-07-26: iniciado el catálogo versionado de sensores y la recuperación de valores actuales desde InfluxDB.
- 2026-07-26: recuperación verificada después de reiniciar el backend; seis canales reales reaparecen desde InfluxDB y exponen antigüedad y estado obsoleto.
- 2026-07-26: iniciado el consumo del catálogo en frontend y la card numérica `meter`.
- 2026-07-26: frontend dirigido por catálogo y cards `meter` desplegados; seis sensores recuperan estado, antigüedad y condición obsoleta.
- 2026-07-26: corregida la mezcla de módulos antiguos y nuevos en caché mediante versionado de imports y `Cache-Control: no-store`.
- 2026-07-26: aclarada la fuente de verdad actual: `zro-pi` en `pihomeblk-1`; Home Assistant pertenece solo al histórico previo.
- 2026-07-26: iniciado el bridge MQTT RPi → VPS mediante Tailscale para `/ZRO/env/#`.
- 2026-07-26: bridge verificado con siete retained; iniciada la adaptación del contrato `zro-pi` al esquema histórico `home/{ubicación}/{medida}`.
- 2026-07-26: adaptador desplegado; 16 canales frescos se descubren desde `zro-pi` y se escriben conservando continuidad con el histórico anterior de Home Assistant.
