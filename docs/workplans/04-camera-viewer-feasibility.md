---
status: viable-rtsp-verified
created: 2026-09-18
updated: 2026-09-18
---

# Viabilidad del visor de cámara doméstica

## Resultado confirmado

La cámara **EZVIZ C6N** está en **192.168.1.199**. Después de reconfigurar su Wi-Fi y habilitar RTSP, la Raspberry `pihomeblk-1` pudo autenticarse y consultar el stream mediante `ffprobe`.

| Parámetro | Resultado |
|---|---|
| Origen | `rtsp://192.168.1.199:554/` (requiere autenticación) |
| Transporte probado | RTSP sobre TCP |
| Vídeo | H.264, 1920 × 1080 |
| Audio | AAC, 16 kHz, mono |
| Credenciales | Facilitadas por el usuario y verificadas; no guardadas en Git |
| Validación realizada | Autenticación y consulta de streams; sin capturas ni grabaciones |
| Pendiente | Reproducción en navegador, latencia, bitrate y consumo de recursos |

**La integración es viable.** H.264/AAC permite plantear una pasarela MSE/fMP4 sin recodificar. Todavía no se ha instalado go2rtc ni implementado el widget. El plan de ejecución está en [05-camera-dashboard-widget.md](05-camera-dashboard-widget.md).

## Arquitectura seleccionada para planificar

```text
EZVIZ C6N → RTSP/TCP → go2rtc en pihomeblk-1
                              ↓ MSE/fMP4 por WebSocket sobre Tailscale
                         Nginx en charo-vps
                              ↓ mismo origen del dashboard
                         widget React
```

El vídeo viajará por una ruta específica de reproducción, independiente del WebSocket de sensores. No se almacenará en InfluxDB ni se transportará por MQTT. No requiere reinstalar Home Assistant ni usar la nube de EZVIZ.

MSE es la primera opción porque permite aprovechar el proxy HTTP/WebSocket existente. La documentación de go2rtc describe su integración en aplicaciones propias y esa salida. WebRTC queda como alternativa si las pruebas muestran que hace falta menor latencia: su transporte de medios requiere una ruta adicional, no basta con el proxy HTTP. HLS se evaluará si lo exige un navegador móvil objetivo.

## Recursos y condiciones

- La Pi es ARM64 y, durante el diagnóstico, tenía unos 590 MB de RAM disponible y 693 MB de swap utilizada. Esa medición es puntual, no un presupuesto permanente.
- Priorizar reutilización del H.264 original. No introducir transcodificación continua sin medir su impacto en zro-pi y Zigbee2MQTT.
- El vídeo se solicitará solo al pulsar «View live» y se cerrará cuando deje de verse.
- A 1 Mbit/s se transmiten aproximadamente 450 MB/h, sin overhead. El bitrate real y el comportamiento con varios espectadores quedan por medir.
- Recomendar reserva DHCP de `.199`, vinculada a la MAC actual de la cámara, para evitar otra búsqueda tras reiniciar. No se ha configurado el router.
- Falta comprobar que RTSP permanece habilitado después de un reinicio normal. No hacer resets para esta prueba.

## Diagnóstico histórico resuelto

Las primeras IP propuestas (`.129`, `.130`, `.162` y `.186`) no ofrecieron un stream accesible. En `.199`, inicialmente 8000 estaba abierto y 554 cerrado. Durante la reconfiguración la cámara salió de la LAN; después del reset y reconexión realizados por el usuario, RTSP funcionó en `.199`.

Se inspeccionó sin restaurarla la copia `C:/Users/joser/Work/ZRO home assistant/automatic_backup_2025_9_4.tar`, creada el 2025-09-26. Contenía dos C6N, una integración cloud y una URL RTSP autenticada del observatorio (`10.8.2.38`), pero no una IP doméstica recuperable útil. Las MAC antiguas no coincidían con la cámara actual. No se usaron las sesiones cloud del backup ni se guardaron sus contraseñas en el proyecto. La copia temporal del histórico consultado se eliminó.

Estas pruebas antiguas no describen el estado actual: **el acceso RTSP autenticado a `.199` ya está confirmado**.

## Fuentes primarias consultadas

- [EZVIZ: C6N/TY1/TY2 mediante RTSP](https://support.ezviz.com/faq/article/How-to-set-up-C6N-TY1-TY2-as-a-webcam).
- [EZVIZ: soporte C6N y configuración local](https://support.ezviz.com/product/C6N/9046).
- [go2rtc: protocolos, despliegue y seguridad](https://github.com/AlexxIT/go2rtc).
- [go2rtc: integración del reproductor](https://github.com/AlexxIT/go2rtc/blob/master/www/README.md).
- [go2rtc: MSE/fMP4](https://github.com/AlexxIT/go2rtc/blob/master/internal/mp4/README.md).
- [go2rtc: transporte WebRTC](https://github.com/AlexxIT/go2rtc/blob/master/internal/webrtc/README.md).
