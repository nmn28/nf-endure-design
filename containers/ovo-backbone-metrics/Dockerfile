# ovo-backbone-metrics:v1 — CPU-only backbone quality metrics for RunPod Serverless
# Computes: radius of gyration, contact order, steric clashes, backbone geometry

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends procps && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    biopython \
    numpy \
    scipy \
    runpod \
    boto3

COPY handler.py /opt/handler.py

ENTRYPOINT []
CMD ["python", "-u", "/opt/handler.py"]
