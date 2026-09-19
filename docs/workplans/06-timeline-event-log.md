---
status: implemented
created: 2026-09-19
updated: 2026-09-19
---

# Log de últimos eventos en las tarjetas de timeline

Decisiones confirmadas por el usuario el 2026-09-19: una fila por intervalo, el log sigue a la ventana visible y aviso explícito de eventos anteriores al periodo. Implementado el mismo día; ver [Implementación](#implementación-2026-09-19).

## Objetivo y alcance

Añadir a cada tarjeta de timeline —puerta y vibración— una lista con los **cinco eventos más recientes** del periodo seleccionado, bajo la barra de la línea temporal. La barra responde bien a «cuánto y cuándo» de un vistazo, pero no a «¿a qué hora se abrió la última vez y cuánto estuvo abierta?», que hoy obliga a pasar el puntero por encima o a hacer zoom.

Alcance: presentación en el frontend. No hace falta endpoint nuevo, consulta adicional a InfluxDB ni cambio en el backend.

## Por qué no hace falta backend

`GET /api/intervals?sensor_id=…&range=…` ya devuelve **todos** los intervalos del rango, y `EventTimelineCard` ya los tiene cargados para pintar la barra; incluso recalcula `visibleIntervals` con las marcas recortadas a la ventana visible. El log es otra lectura de esos mismos datos.

Esto también fija qué es un «evento». Un intervalo es una apertura completa (inicio, fin y duración) o un episodio de vibración; la alternativa sería listar transiciones sueltas, que daría dos filas por apertura —«abierta» y «cerrada»— sin decir cuánto duró. Se elige **una fila por intervalo**: más informativa y coherente con lo que ya dibuja la barra.

Consecuencia deliberada: no se listan los cierres como eventos propios. Si más adelante se quisieran avisos o registro de cierres, habría que revisar esta decisión.

## Experiencia en el dashboard

Bajo la barra de la timeline, dentro de la misma tarjeta. Texto en inglés, como el resto del dashboard.

- Encabezado discreto: `Recent events`.
- Cinco filas como máximo, **de más reciente a más antigua**.
- Cada fila: hora de inicio, duración y, si sigue en curso, marca explícita.
  - Puerta: `09:11:55 · open for 3m 50s` — en curso: `09:11:55 · open now · 12m`.
  - Vibración: `Detected 18:04:12 · 4s`.
- La fecha aparece solo cuando el periodo abarca más de un día, con el mismo criterio que `formatTick`, para no repetir «19 Sep» cinco veces en un rango de 1 h.
- Horas en la zona del navegador, como el resto del dashboard.
- Sin eventos: `No events in this period`, no una lista vacía.
- Mientras carga: no mostrar una lista vacía que parezca «no ha pasado nada»; reutilizar el estado de carga de la tarjeta.
- La tarjeta ya indica el total (`N events`) en su descripción; el log no lo repite. Si hay más de cinco, indicar que se muestran los cinco últimos de ese total.

### Decisión: el log sigue a la ventana visible

La petición era «los 5 últimos del periodo seleccionado en el dashboard». Sin zoom, la ventana visible **es** el periodo seleccionado, así que coinciden. Con zoom temporal activo, el log seguirá a la ventana visible en lugar de al rango global.

El motivo es la coherencia dentro de la tarjeta: la descripción ya cuenta eventos y minutos activos de la ventana visible (`visibleIntervals`). Un log que contara otra cosa que el contador de su propia tarjeta sería un error de lectura garantizado. La tarjeta ya rotula `Temporary zoom` cuando ese estado está activo.

Si en revisión se prefiere lo contrario, el cambio es una línea: usar `timeline.intervals` en vez de `visibleIntervals`.

### Recorte en los bordes del rango

`build_intervals` solo abre un intervalo cuando ve la transición de entrada dentro del rango: una puerta abierta **antes** del inicio del periodo no aparece, y la reconstrucción del estado anterior sigue pendiente (anotada en [01-dashboard-domotico.md](01-dashboard-domotico.md) y en `claude.md`).

Con la barra esto se nota poco; en una lista de «últimos eventos» es una ausencia que el usuario puede interpretar como «no pasó nada». Para no mentir: cuando el intervalo más antiguo visible empiece exactamente en el inicio de la ventana, o cuando el rango no alcance ningún evento, el log debe poder decirlo con una nota discreta del tipo `Earlier events may fall outside this period`. No inventar un evento reconstruido en el frontend: esa reconstrucción es trabajo del backend y tiene su propia tarea pendiente.

## Implementación prevista

| Área | Cambio |
|---|---|
| `frontend-react/src/lib/timeline-events.ts` | Función pura `recentEvents(intervals, limit)` y formateo de duración |
| `frontend-react/src/components/event-timeline-card.tsx` | Sección `Recent events` bajo la barra |

Función pura y en `lib/`, no incrustada en el componente: es la única parte con lógica real —orden, recorte, duración, evento en curso— y así queda verificable sin renderizar. El componente se limita a presentar.

Detalles a respetar:

- Ordenar por inicio descendente sobre `visibleIntervals`, que ya viene recortado a la ventana.
- La duración se calcula con las marcas recortadas (`visibleStart`/`visibleEnd`), igual que `totalMs`, para que la suma de las filas sea consistente con los minutos activos que muestra la tarjeta.
- Un intervalo con `active: true` está en curso: su fin es «ahora» y la duración debe refrescarse, no quedarse congelada al montar.
- La lista se actualiza sola: el efecto que consulta `/api/intervals` ya depende de `sensor.current.updated_at`, así que cada lectura nueva por WebSocket la refresca. No añadir temporizadores propios salvo para la duración del evento en curso.
- Marcado semántico: lista ordenada (`<ol>`) con `<time dateTime=…>`, no un conjunto de `<div>`. Es contenido que se lee, no decoración.

## Pruebas y criterios de aceptación

- Cinco filas como máximo, la más reciente arriba, coherentes con lo que dibuja la barra.
- La suma de duraciones de las filas nunca supera los minutos activos que declara la tarjeta.
- Un evento en curso aparece marcado como tal y su duración avanza sin recargar.
- Una apertura nueva recibida por WebSocket aparece en el log sin intervención.
- Al hacer zoom, log y contador de la tarjeta hablan del mismo conjunto; al soltar el zoom, vuelven al rango completo.
- Periodo sin eventos: mensaje explícito, no lista vacía.
- Rangos largos (`7d`, `30d`, `forever`): la fecha aparece y el ancho no desborda en móvil.
- Temas claro y oscuro, navegación con teclado y lectura con lector de pantalla.
- `npm run typecheck` y `npm run build` correctos.

La verificación automática de `recentEvents` depende de la decisión pendiente de añadir runner de pruebas al frontend, anotada en [05-camera-dashboard-widget.md](05-camera-dashboard-widget.md). Hasta entonces la comprobación es manual y la función queda aislada para poder probarla en cuanto exista runner.

## Fuera de alcance

Paginación o histórico completo, exportación, filtros por tipo de evento, resaltar en la barra el intervalo de la fila señalada, y listar los cierres como eventos propios. Ninguno hace falta para responder «qué ha pasado últimamente aquí».


## Implementación (2026-09-19)

`frontend-react/src/lib/timeline-events.ts` con `recentEvents(intervals, limit, now)`, `formatDuration` y `formatEventTime`, y la sección `Recent events` al final de `EventTimelineCard`. Sin cambios en el backend, como preveía el plan: ni un endpoint ni una consulta más.

### Un cambio sobre lo planeado

Al probar la función apareció que el criterio «la suma de duraciones del log nunca supera los minutos activos de la tarjeta» se incumplía en cuanto había un evento en curso: el log avanzaba en vivo mientras `active minutes` seguía congelado en el instante de la consulta. A los dos minutos y medio, log 15 min contra contador 13 min dentro de la misma tarjeta.

Se corrige en la raíz en vez de retocar el texto: la descripción de la tarjeta y el log salen ahora de la misma derivación (`recentEvents` sobre todos los intervalos, el log es su recorte a cinco). La coherencia deja de ser algo que haya que recordar mantener y pasa a ser estructural.

### Detalles resueltos

- El reloj de un segundo solo corre mientras hay un evento en curso; es el único caso cuya etiqueta envejece sola, y la tarjeta es cara de repintar.
- Un intervalo abierto cuyo final recorta el zoom deja de contar como «en curso»: se muestra su duración recortada, porque en esa ventana no está pasando ahora.
- `LONG_SPAN_MS` se comparte con `formatTick` para que el criterio de mostrar fecha sea uno solo.
- Las filas son `<ol>` con `<time dateTime>`; la nota `(started earlier)` marca el evento recortado por el borde del periodo.

### Verificación

`npm run typecheck` y `npm run build` correctos. La lógica se comprobó compilando el módulo y ejercitándolo con casos reales: orden descendente, duración de un evento en curso que avanza más allá del instante de la consulta, recorte por el borde del periodo, corte por zoom, límite de cinco, lista vacía y formateo de duraciones de 1 s a más de un día. Queda pendiente la comprobación en navegador y el runner de pruebas del frontend, que sigue sin decidirse.
