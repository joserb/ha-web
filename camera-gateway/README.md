# Pasarela de cámara (go2rtc en `pihomeblk-1`)

Convierte el RTSP de la EZVIZ C6N en fMP4 sobre WebSocket para que el
dashboard lo reproduzca con MSE. Vive en la Raspberry, no en el VPS: así el
vídeo no atraviesa FastAPI, MQTT ni InfluxDB, y el enlace por Tailscale
transporta ya el formato final.

```text
C6N ──RTSP/TCP── go2rtc (pihomeblk-1) ──MSE/fMP4 por WS sobre Tailscale──
     Nginx (charo-vps) ──mismo origen── dashboard React
```

## Instalación

En la Pi vive junto a `zro-pi`, en el directorio del usuario:

```bash
cd ~/camera-gateway
cp .env.example .env                  # IP Tailscale de la Pi
cp go2rtc.yaml.example go2rtc.yaml    # URL RTSP con credenciales
sudo chown root:root go2rtc.yaml      # imprescindible, ver abajo
sudo chmod 600 go2rtc.yaml
docker compose up -d
```

El propietario tiene que ser `root`. El contenedor corre como root pero con
`cap_drop: ALL`, es decir, sin `CAP_DAC_OVERRIDE`: solo puede leer el fichero
si es su propietario. Con otro dueño y modo 600 go2rtc **no avisa**, arranca
con los valores por defecto y deja expuestas la interfaz web y `/api/streams`,
que devuelve la URL de origen con credenciales. El healthcheck comprueba
justamente eso, así que un fichero ilegible sale como `unhealthy`.

Editar después con `sudo -e go2rtc.yaml` y `docker compose restart go2rtc`.

`go2rtc.yaml` y `.env` están en `.gitignore`. La URL RTSP autenticada no debe
copiarse a ningún otro fichero del repositorio ni llegar al navegador.

## Comprobaciones tras arrancar

Desde la propia Pi:

```bash
docker compose ps                     # healthy
docker compose logs --tail 50 go2rtc  # sin bucles de reconexión
```

Desde el VPS, por Tailscale (`GATEWAY_BIND_IP` es la IP de la Pi):

```bash
# 400 Bad Request es la respuesta correcta: el endpoint existe y exige upgrade.
curl -s -o /dev/null -w '%{http_code}\n' http://GATEWAY_BIND_IP:1984/api/ws

# 404 en todo lo demás: interfaz web, configuración y listado de fuentes.
for path in / api api/config api/streams api/frame.mp4 api/stream.mp4; do
  printf '%s -> ' "$path"
  curl -s -o /dev/null -w '%{http_code}\n' "http://GATEWAY_BIND_IP:1984/$path"
done
```

Que `/api/streams` responda 404 importa: esa ruta devuelve la configuración de
las fuentes, incluida la URL de origen.

## Consumo bajo demanda

go2rtc solo abre el RTSP cuando llega el primer espectador y lo cierra cuando
sale el último. Para comprobarlo, con el dashboard cerrado no debe haber
conexión establecida hacia la cámara:

```bash
docker compose exec go2rtc sh -c 'netstat -tn 2>/dev/null | grep 192.168.1.199 || echo "sin conexión a la cámara"'
```

Repetir con la tarjeta abierta: debe aparecer una conexión al puerto 554, y
desaparecer unos segundos después de pulsar Stop.

## Medición antes de darlo por bueno

Registrar arranque, bitrate, CPU y memoria en la Pi con un espectador y con
dos (`docker stats ha-web-camera-gateway`). La Pi comparte CPU con zro-pi y
Zigbee2MQTT y durante el diagnóstico usaba swap: si el consumo sube, revisar
si existe un substream de menor resolución antes de plantear recodificar.
Recodificar de forma continua no entra en esta entrega.

## Parada y reversión

```bash
docker compose down        # el dashboard sigue funcionando; la tarjeta dará error
```

Para ocultar además la tarjeta, poner `CAMERA_ENABLED=false` en el `.env` del
VPS y recrear el contenedor `nginx` de ha-web. La pasarela puede detenerse sin
tocar Mosquitto, InfluxDB, el backend ni zro-pi.
