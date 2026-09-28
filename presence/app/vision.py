"""Personas (NanoDet), caras (YuNet) y embeddings (SFace), todo con OpenCV DNN.

Modelos de OpenCV Zoo, descargados en la imagen con hash fijado (Dockerfile).
Una cara a 4–5 m mide unas decenas de píxeles en 1080p: por eso las caras se
buscan a resolución completa dentro de la parte alta de cada persona, y solo
una pasada global a media resolución recoge las caras cercanas sin persona.
"""
from pathlib import Path

import cv2
import numpy as np

from app.tracking import Detection, FaceSample

PERSON_CLASS = 0
# 0,35 es el valor de la demo de OpenCV Zoo. Con 0,4, una persona de espaldas
# con infrarrojo (0,47–0,54 medido el 2026-09-28) caía bajo el umbral en
# frames sueltos y su recorrido se partía en dos trayectorias.
PERSON_THRESHOLD = 0.35
FACE_THRESHOLD = 0.7
NANODET_SIZE = 416
REG_MAX = 7
HEAD_FRACTION = 0.45
MIN_HEAD_WIDTH = 160
MAX_HEAD_WIDTH = 480
CROP_MAX_SIDE = 160


class Vision:
    def __init__(self, models_dir: str):
        # El análisis comparte VPS con todo lo demás: un solo hilo por modelo.
        cv2.setNumThreads(1)
        models = Path(models_dir)
        self.persons_net = cv2.dnn.readNet(str(models / "object_detection_nanodet_2022nov.onnx"))
        self.face_detector = cv2.FaceDetectorYN.create(
            str(models / "face_detection_yunet_2023mar.onnx"), "", (320, 320), FACE_THRESHOLD, 0.3, 20)
        self.recognizer = cv2.FaceRecognizerSF.create(str(models / "face_recognition_sface_2021dec.onnx"), "")
        self.mean = np.array([103.53, 116.28, 123.675], dtype=np.float32).reshape(1, 1, 3)
        self.std = np.array([57.375, 57.12, 58.395], dtype=np.float32).reshape(1, 1, 3)

    # --- Personas -----------------------------------------------------------

    def persons(self, frame: np.ndarray) -> list[tuple[tuple[float, float, float, float], float]]:
        height, width = frame.shape[:2]
        scale = NANODET_SIZE / max(height, width)
        resized = cv2.resize(frame, (round(width * scale), round(height * scale)))
        letterbox = np.zeros((NANODET_SIZE, NANODET_SIZE, 3), np.uint8)
        letterbox[:resized.shape[0], :resized.shape[1]] = resized
        blob = cv2.dnn.blobFromImage((letterbox.astype(np.float32) - self.mean) / self.std)
        self.persons_net.setInput(blob)
        outputs = self.persons_net.forward(self.persons_net.getUnconnectedOutLayersNames())
        boxes, scores = self._decode_nanodet(outputs)
        if not len(boxes):
            return []
        wh = boxes.copy()
        wh[:, 2:] -= wh[:, :2]
        keep = cv2.dnn.NMSBoxes(wh.tolist(), scores.tolist(), PERSON_THRESHOLD, 0.5)
        result = []
        for index in np.array(keep).flatten():
            x0, y0, x1, y1 = boxes[index] / scale
            result.append(((max(0.0, x0), max(0.0, y0), min(width, x1), min(height, y1)), float(scores[index])))
        return result

    @staticmethod
    def _decode_nanodet(outputs) -> tuple[np.ndarray, np.ndarray]:
        """Empareja salidas por forma, no por orden: OpenCV 4 y 5 las devuelven
        en órdenes distintos. Cada nivel tiene (N, 80) clases y (N, 32) cajas."""
        levels: dict[int, dict[str, np.ndarray]] = {}
        for output in outputs:
            output = output.reshape(output.shape[-2], output.shape[-1])
            kind = "cls" if output.shape[1] == 80 else "box"
            levels.setdefault(output.shape[0], {})[kind] = output
        project = np.arange(REG_MAX + 1, dtype=np.float32)
        all_boxes, all_scores = [], []
        for count, level in levels.items():
            side = int(round(count ** 0.5))
            stride = NANODET_SIZE // side
            scores = level["cls"][:, PERSON_CLASS]
            mask = scores >= PERSON_THRESHOLD
            if not mask.any():
                continue
            distribution = level["box"][mask].reshape(-1, REG_MAX + 1)
            distribution = np.exp(distribution - distribution.max(axis=1, keepdims=True))
            distribution /= distribution.sum(axis=1, keepdims=True)
            distances = (distribution @ project).reshape(-1, 4) * stride
            indices = np.nonzero(mask)[0]
            cx = (indices % side) * stride + 0.5 * (stride - 1)
            cy = (indices // side) * stride + 0.5 * (stride - 1)
            boxes = np.column_stack([cx - distances[:, 0], cy - distances[:, 1],
                                     cx + distances[:, 2], cy + distances[:, 3]])
            all_boxes.append(np.clip(boxes, 0, NANODET_SIZE))
            all_scores.append(scores[mask])
        if not all_boxes:
            return np.empty((0, 4)), np.empty(0)
        return np.concatenate(all_boxes), np.concatenate(all_scores)

    # --- Caras --------------------------------------------------------------

    def _faces(self, image: np.ndarray) -> np.ndarray:
        self.face_detector.setInputSize((image.shape[1], image.shape[0]))
        _, faces = self.face_detector.detect(image)
        return np.empty((0, 15), np.float32) if faces is None else faces

    def _sample(self, frame: np.ndarray, face: np.ndarray) -> FaceSample:
        height, width = frame.shape[:2]
        aligned = self.recognizer.alignCrop(frame, face)
        embedding = self.recognizer.feature(aligned).flatten()
        x, y, w, h = face[:4]
        margin = 0.4 * max(w, h)
        x0, y0 = int(max(0, x - margin)), int(max(0, y - margin))
        x1, y1 = int(min(width, x + w + margin)), int(min(height, y + h + margin))
        crop = frame[y0:y1, x0:x1]
        factor = CROP_MAX_SIDE / max(crop.shape[:2])
        if factor < 1:
            crop = cv2.resize(crop, (round(crop.shape[1] * factor), round(crop.shape[0] * factor)))
        ok, jpeg = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return FaceSample(
            embedding=tuple(float(value) for value in embedding),
            quality=float(w * h) / (width * height) * float(face[-1]),
            jpeg=jpeg.tobytes() if ok else b"",
        )

    def _face_in_head(self, frame: np.ndarray, box) -> np.ndarray | None:
        """Mejor cara en la parte alta de una persona, en coordenadas del frame."""
        x0, y0, x1, y1 = box
        pad = 0.1 * (x1 - x0)
        hx0, hx1 = int(max(0, x0 - pad)), int(min(frame.shape[1], x1 + pad))
        hy0, hy1 = int(max(0, y0 - pad)), int(min(frame.shape[0], y0 + HEAD_FRACTION * (y1 - y0)))
        if hx1 - hx0 < 8 or hy1 - hy0 < 8:
            return None
        head = frame[hy0:hy1, hx0:hx1]
        # Cabezas lejanas se amplían para YuNet; cercanas se reducen, que una
        # cara grande no necesita resolución y el detector escala con el área.
        factor = min(max(1.0, MIN_HEAD_WIDTH / head.shape[1]), MAX_HEAD_WIDTH / head.shape[1])
        if factor != 1:
            head = cv2.resize(head, (round(head.shape[1] * factor), round(head.shape[0] * factor)))
        faces = self._faces(head)
        if not len(faces):
            return None
        face = faces[np.argmax(faces[:, -1])].copy()
        face[:14] /= factor
        face[0:14:2] += hx0
        face[1:14:2] += hy0
        return face

    # --- Frame completo -----------------------------------------------------

    def analyze(self, frame: np.ndarray) -> list[Detection]:
        height, width = frame.shape[:2]

        def normalized(box):
            return (float(box[0]) / width, float(box[1]) / height, float(box[2]) / width, float(box[3]) / height)

        detections = []
        person_boxes = self.persons(frame)
        for box, score in person_boxes:
            face = self._face_in_head(frame, box)
            sample = self._sample(frame, face) if face is not None else None
            detections.append(Detection(normalized(box), score, sample))

        half = cv2.resize(frame, (width // 2, height // 2))
        for face in self._faces(half):
            face = face.copy()
            face[:14] *= 2
            cx, cy = face[0] + face[2] / 2, face[1] + face[3] / 2
            if any(b[0] <= cx <= b[2] and b[1] <= cy <= b[3] for b, _ in person_boxes):
                continue
            x, y, w, h = face[:4]
            # Sin cuerpo detectado: caja aproximada de la persona desde la cara.
            box = (max(0, x - w), max(0, y - 0.5 * h), min(width, x + 2 * w), min(height, y + 6 * h))
            detections.append(Detection(normalized(box), float(face[-1]), self._sample(frame, face)))
        return detections
