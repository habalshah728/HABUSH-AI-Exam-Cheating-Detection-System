FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libegl1 \
    libgles2 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libgomp1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

ENV OMP_NUM_THREADS=2 \
    MKL_NUM_THREADS=2 \
    OPENBLAS_NUM_THREADS=2 \
    NUMEXPR_NUM_THREADS=2 \
    MALLOC_ARENA_MAX=2 \
    YOLO_VERBOSE=False \
    YOLO_CONFIG_DIR=/tmp/ultralytics \
    MPLCONFIGDIR=/tmp/matplotlib

COPY requirements.txt .
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchvision && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data/uploads data/logs evidence reports models /tmp/ultralytics /tmp/matplotlib && \
    chmod -R 777 data evidence reports models /tmp/ultralytics /tmp/matplotlib && \
    chmod -R a+rX /app

EXPOSE 8000
CMD ["sh", "-c", "uvicorn web_app:app --host 0.0.0.0 --port ${PORT:-8000}"]
