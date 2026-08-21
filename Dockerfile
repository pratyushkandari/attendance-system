# ================= MULTI-STAGE PYTHON DOCKERFILE =================
FROM python:3.10-slim AS base

# Set environment variables for minimal RAM consumption
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    VECLIB_MAXIMUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1

WORKDIR /app

# Install minimal essential system libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 1. Install lightweight CPU-only PyTorch build (saves >400MB RAM)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

# 2. Install remaining requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Expose Web & Metrics Port
EXPOSE 5000

# Start Production Multi-Threaded Gunicorn WSGI Server
CMD ["python", "run.py"]

