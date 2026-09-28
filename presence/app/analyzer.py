"""Un análisis por apertura de puerta, en un hilo propio.

Ventana: desde `apertura − pre-roll` hasta `cierre + post-roll`, con tope si la
puerta se queda abierta. Una nueva apertura durante el post-roll prolonga el
mismo evento: quien entra y vuelve a salir a por algo es un solo recorrido.
"""
import logging
import queue
import threading
import time
from typing import Callable

import av

from app.config import Settings
from app.inference import Window, describe, summarize
from app.store import PresenceStore
from app.stream import CameraStream
from app.tracking import Tracker

logger = logging.getLogger(__name__)

# Tras el final de la ventana se espera a que lleguen sus últimos paquetes;
# si el vídeo se ha parado, se cierra el análisis con lo que haya.
STALL_SECONDS = 10


class Analyzer(threading.Thread):
    def __init__(self, settings: Settings, stream: CameraStream | None, store: PresenceStore,
                 on_event: Callable[[dict], None]):
        super().__init__(name="presence-analyzer", daemon=True)
        self.settings = settings
        self.stream = stream
        self.store = store
        self.on_event = on_event
        self.doors: queue.Queue[tuple[str, float]] = queue.Queue()
        # Apertura leída durante un análisis pero posterior a su ventana.
        self.carry: tuple[str, float] | None = None
        self.vision = None
        self.busy = False
        self.last_error: str | None = None

    def door(self, state: str, timestamp: float):
        """Llamado desde el bucle MQTT; seguro entre hilos."""
        self.doors.put((state, timestamp))

    def _next(self) -> tuple[str, float]:
        if self.carry is not None:
            item, self.carry = self.carry, None
            return item
        return self.doors.get()

    def run(self):
        if self.stream is not None:
            # Al arrancar y no en el primer evento: un modelo que falta tiene
            # que verse ya, no cuando alguien cruza la puerta.
            from app.vision import Vision  # OpenCV solo se carga si hay cámara.
            self.vision = Vision(self.settings.models_dir)
        while True:
            state, timestamp = self._next()
            if state != "open":
                continue
            self.busy = True
            try:
                self._event(timestamp)
                self.last_error = None
            except Exception as exc:
                logger.exception("Presence analysis failed")
                self.last_error = type(exc).__name__
            finally:
                self.busy = False

    def _event(self, opened_at: float):
        settings = self.settings
        closed_at: float | None = None
        tracker = Tracker()
        frames = 0

        if self.stream is not None:
            self.stream.acquire()
            try:
                frames, closed_at = self._watch(opened_at, tracker)
            finally:
                self.stream.release()
        else:
            closed_at = self._wait_close(opened_at)

        window = Window(opened_at, closed_at, settings.door_zone)
        results = summarize(tracker.tracks(), window, self.store.gallery(), settings.match_threshold)
        status = "no_video" if frames == 0 else ("ok" if results else "nobody_seen")
        now = time.time()
        event_id = self.store.record_event(opened_at, closed_at, now, status, frames, results)
        text = describe(self.store.event_lines(event_id), status)
        logger.info("Presence event %d: %s (%d frames)", event_id, status, frames)
        self.on_event({"event_id": event_id, "time": now, "status": status, "text": text,
                       "sensor_id": settings.door_sensor_id})

    def _door_updates(self, closed_at: float | None,
                      last_open: float) -> tuple[float | None, float]:
        """Consume transiciones pendientes. Devuelve (cierre, última apertura)."""
        while self.carry is None:
            try:
                state, timestamp = self.doors.get_nowait()
            except queue.Empty:
                break
            if state == "closed" and timestamp >= last_open:
                closed_at = timestamp
            elif state == "open":
                if timestamp > self._end(closed_at, last_open):
                    # Fuera de la ventana: es el evento siguiente.
                    self.carry = (state, timestamp)
                else:
                    closed_at, last_open = None, timestamp
        return closed_at, last_open

    def _end(self, closed_at: float | None, last_open: float) -> float:
        if closed_at is not None:
            return closed_at + self.settings.postroll_seconds
        return last_open + self.settings.max_open_seconds + self.settings.postroll_seconds

    def _wait_close(self, opened_at: float) -> float | None:
        """Sin cámara configurada solo se registra el evento, sin análisis."""
        closed_at, last_open = None, opened_at
        while time.time() < self._end(closed_at, last_open) and self.carry is None:
            closed_at, last_open = self._door_updates(closed_at, last_open)
            if closed_at is not None:
                return closed_at
            time.sleep(0.5)
        return closed_at

    def _watch(self, opened_at: float, tracker: Tracker) -> tuple[int, float | None]:
        settings, stream = self.settings, self.stream
        delay = settings.video_delay_seconds
        start = opened_at - settings.preroll_seconds
        interval = 1 / settings.analysis_fps
        seq = stream.start_seq(start + delay)
        closed_at, last_open = None, opened_at
        decoder, generation = None, None
        last_analysed, frames, last_packet = float("-inf"), 0, time.time()

        while True:
            closed_at, last_open = self._door_updates(closed_at, last_open)
            end = self._end(closed_at, last_open)
            entries = stream.read_from(seq, timeout=0.5)
            if not entries:
                if time.time() > end + delay + STALL_SECONDS or (
                        time.time() - last_packet > STALL_SECONDS and time.time() > end):
                    return frames, closed_at
                continue
            last_packet = time.time()
            for entry in entries:
                seq = entry.seq + 1
                # Hora aproximada de captura: la llegada menos el retraso del
                # camino cámara → Pi → Tailscale → VPS.
                t = entry.wall - delay
                if t > end:
                    return frames, closed_at
                if entry.generation != generation:
                    # Reconexión: nuevo decodificador y a esperar un keyframe.
                    if not entry.packet.is_keyframe:
                        continue
                    decoder = av.CodecContext.create("h264", "r")
                    decoder.extradata = stream.codec_extradata(entry.generation)
                    generation = entry.generation
                try:
                    decoded = decoder.decode(entry.packet)
                except av.error.FFmpegError:
                    continue
                for frame in decoded:
                    if t < start or t - last_analysed < interval:
                        continue
                    last_analysed = t
                    frames += 1
                    tracker.update(t, self.vision.analyze(frame.to_ndarray(format="bgr24")))
