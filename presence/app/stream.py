"""Lectura del vídeo de go2rtc con memoria de los últimos segundos (pre-roll).

Quien sale de casa cruza la escena ANTES de abrir la puerta, así que empezar a
mirar al recibir la apertura llegaría tarde. El hilo mantiene abierto el mismo
WebSocket MSE que usa el dashboard y guarda los paquetes H.264 de los últimos
segundos **sin decodificar**: demultiplexar fMP4 cuesta casi nada, decodificar
1080p de forma continua no. Solo se decodifica cuando hay un evento.

Con `PRESENCE_PREROLL_SECONDS=0` la conexión se abre bajo demanda al abrirse
la puerta y se suelta al terminar el análisis.
"""
import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass

import av
from websockets.sync.client import connect

logger = logging.getLogger(__name__)

# go2rtc escoge entre los que ofrece el cliente; la C6N entrega H.264 Main.
CODECS = "avc1.640029,avc1.64002A,avc1.640033,avc1.4D0029,avc1.4D002A,avc1.42E01E"
# Un GOP de la C6N dura ~4,8 s: se guarda margen para empezar siempre en un
# keyframe anterior al inicio de la ventana.
GOP_MARGIN_SECONDS = 10
ACTIVE_EXTRA_SECONDS = 180
# Sin datos durante este tiempo, la conexión se da por congelada.
READ_TIMEOUT_SECONDS = 15
# En modo bajo demanda, cuánto se mantiene abierta tras el último análisis.
LINGER_SECONDS = 30


class GatewayError(Exception):
    pass


@dataclass(frozen=True)
class Entry:
    seq: int
    wall: float
    generation: int
    packet: av.Packet


class _WebSocketReader:
    """Objeto fichero para PyAV: bloquea hasta el siguiente fragmento fMP4."""

    def __init__(self, ws, stopped: threading.Event):
        self.ws = ws
        self.stopped = stopped
        self.buffer = b""
        self.error: Exception | None = None

    def read(self, size: int) -> bytes:
        try:
            while not self.buffer:
                if self.stopped.is_set():
                    return b""
                message = self.ws.recv(timeout=READ_TIMEOUT_SECONDS)
                if isinstance(message, str):
                    # El texto de error de go2rtc incluye IP y puerto internos:
                    # no se propaga, igual que en el dashboard.
                    if json.loads(message).get("type") == "error":
                        raise GatewayError("The gateway could not reach the camera")
                    continue
                self.buffer = message
        except Exception as exc:  # PyAV no propaga bien excepciones del callback.
            self.error = exc
            return b""
        chunk, self.buffer = self.buffer[:size], self.buffer[size:]
        return chunk


class CameraStream(threading.Thread):
    def __init__(self, url: str, preroll_seconds: float):
        super().__init__(name="camera-stream", daemon=True)
        self.url = url
        self.always_on = preroll_seconds > 0
        self.keep_seconds = preroll_seconds + GOP_MARGIN_SECONDS
        self.cond = threading.Condition()
        self.entries: deque[Entry] = deque()
        self.extradata: dict[int, bytes] = {}
        self.seq = 0
        self.generation = 0
        self.demand = 0
        self.last_demand = 0.0
        self.connected = False
        self.last_error: str | None = None
        self.stopped = threading.Event()

    # --- Interfaz para el análisis -----------------------------------------

    def acquire(self):
        with self.cond:
            self.demand += 1
            self.last_demand = time.time()
            self.cond.notify_all()

    def release(self):
        with self.cond:
            self.demand = max(0, self.demand - 1)
            self.last_demand = time.time()

    def start_seq(self, since: float) -> int:
        """Último keyframe no posterior a `since`; si no queda, el primero."""
        with self.cond:
            keyframes = [entry for entry in self.entries if entry.packet.is_keyframe]
            before = [entry for entry in keyframes if entry.wall <= since]
            if before:
                return before[-1].seq
            if keyframes:
                return keyframes[0].seq
            return self.seq

    def read_from(self, seq: int, timeout: float) -> list[Entry]:
        with self.cond:
            if self.seq <= seq:
                self.cond.wait(timeout)
            return [entry for entry in self.entries if entry.seq >= seq]

    def codec_extradata(self, generation: int) -> bytes | None:
        with self.cond:
            return self.extradata.get(generation)

    def status(self) -> dict:
        with self.cond:
            buffered = self.entries[-1].wall - self.entries[0].wall if len(self.entries) > 1 else 0
        return {
            "connected": self.connected,
            "mode": "preroll" if self.always_on else "on_demand",
            "buffered_seconds": round(buffered, 1),
            "error": self.last_error,
        }

    def stop(self):
        self.stopped.set()
        with self.cond:
            self.cond.notify_all()

    # --- Hilo ---------------------------------------------------------------

    def _wanted(self) -> bool:
        return self.always_on or self.demand > 0 or time.time() - self.last_demand < LINGER_SECONDS

    def run(self):
        backoff = 2.0
        while not self.stopped.is_set():
            if not self._wanted():
                with self.cond:
                    self.cond.wait(1)
                continue
            try:
                self._connection()
                backoff = 2.0
            except Exception as exc:
                message = str(exc) if isinstance(exc, GatewayError) else type(exc).__name__
                if message != self.last_error:
                    logger.warning("Camera stream failed: %s", message)
                self.last_error = message
            self.connected = False
            self.stopped.wait(backoff)
            backoff = min(backoff * 2, 60.0)

    def _connection(self):
        with connect(self.url, open_timeout=10, close_timeout=2, max_size=None) as ws:
            ws.send(json.dumps({"type": "mse", "value": CODECS}))
            reader = _WebSocketReader(ws, self.stopped)
            # Sin probesize pequeño, ffmpeg espera 5 MB antes de abrir: minutos
            # con el bitrate nocturno de la cámara.
            try:
                container = av.open(reader, format="mp4", options={"probesize": "32768", "analyzeduration": "0"})
            except av.error.FFmpegError:
                # Sin datos que abrir: el motivo real es el de la pasarela.
                raise reader.error or GatewayError("Camera stream could not be opened") from None
            try:
                stream = container.streams.video[0]
                with self.cond:
                    self.generation += 1
                    generation = self.generation
                    self.extradata[generation] = bytes(stream.codec_context.extradata or b"")
                    for old in [key for key in self.extradata if key < generation - 1]:
                        del self.extradata[old]
                self.connected = True
                self.last_error = None
                logger.info("Camera stream connected (%s)", "preroll" if self.always_on else "on demand")
                for packet in container.demux(stream):
                    if self.stopped.is_set() or not self._wanted():
                        return
                    if packet.size == 0:
                        continue
                    self._append(packet, generation)
                if reader.error is not None:
                    raise reader.error
                raise GatewayError("Camera stream ended")
            finally:
                container.close()

    def _append(self, packet: av.Packet, generation: int):
        now = time.time()
        with self.cond:
            self.entries.append(Entry(self.seq, now, generation, packet))
            self.seq += 1
            # Mientras hay un análisis se guarda más: si se retrasa (el pre-roll
            # se procesa de golpe), no puede perder los paquetes que le faltan.
            keep = self.keep_seconds + (ACTIVE_EXTRA_SECONDS if self.demand else 0)
            while self.entries and self.entries[0].wall < now - keep:
                self.entries.popleft()
            self.cond.notify_all()
