# ovo-ligandmpnn:v2 — LigandMPNN for RunPod Serverless
# Model weights already baked in rosettacommons base image

FROM nvcr.io/nvidia/pytorch:24.07-py3

# Nextflow/RunPod requires ps (procps), jq for copy_remarks.sh
RUN apt-get update && apt-get install -y --no-install-recommends procps jq && \
    rm -rf /var/lib/apt/lists/*

# Install LigandMPNN (no setup.py — clone repo + install deps separately)
RUN git clone https://github.com/dauparas/LigandMPNN.git /opt/LigandMPNN && \
    pip install --no-cache-dir biopython ProDy scipy ml-collections dm-tree

# Download LigandMPNN model params (not included in repo)
RUN cd /opt/LigandMPNN && \
    bash get_model_params.sh

# Bake OVO bin scripts into container
COPY bin/prepare_json.py /usr/local/bin/prepare_json.py
COPY bin/copy_remarks.sh /usr/local/bin/copy_remarks.sh
RUN chmod +x /usr/local/bin/prepare_json.py /usr/local/bin/copy_remarks.sh

# Install RunPod + boto3
RUN pip install --no-cache-dir runpod boto3

# Copy handler
COPY handler.py /opt/handler.py

ENTRYPOINT []
CMD ["python", "-u", "/opt/handler.py"]
