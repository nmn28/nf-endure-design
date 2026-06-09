FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends dssp && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir runpod boto3 biopython numpy

COPY handler.py /handler.py

CMD ["python3", "/handler.py"]
