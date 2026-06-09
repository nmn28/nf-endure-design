FROM python:3.11-slim

RUN pip install --no-cache-dir runpod boto3 biopython numpy

COPY handler.py /handler.py

CMD ["python3", "/handler.py"]
