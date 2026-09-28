FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Modelos de OpenCV Zoo fijados por commit y hash: YuNet (MIT) detecta caras,
# SFace (Apache-2.0) las describe y NanoDet-Plus (Apache-2.0) detecta personas.
ARG ZOO=https://github.com/opencv/opencv_zoo/raw/47534e27c9851bb1128ccc0102f1145e27f23f98/models
ADD --checksum=sha256:8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4 \
    ${ZOO}/face_detection_yunet/face_detection_yunet_2023mar.onnx /app/models/
ADD --checksum=sha256:0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79 \
    ${ZOO}/face_recognition_sface/face_recognition_sface_2021dec.onnx /app/models/
ADD --checksum=sha256:4b82da9944b88577175ee23a459dce2e26e6e4be573def65b1055dc2d9720186 \
    ${ZOO}/object_detection_nanodet/object_detection_nanodet_2022nov.onnx /app/models/

COPY app/ ./app/
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
