# ovo-rfdiffusion:v2 — RFdiffusion for RunPod Serverless
# Weights baked in for fast cold starts

FROM nvcr.io/nvidia/pytorch:24.07-py3

# Nextflow/RunPod requires ps (procps)
RUN apt-get update && apt-get install -y --no-install-recommends procps && \
    rm -rf /var/lib/apt/lists/*

# Install RFdiffusion (SE3Transformer must be installed from bundled env/ first)
RUN git clone --depth 1 https://github.com/RosettaCommons/RFdiffusion.git /opt/RFdiffusion && \
    pip install --no-cache-dir /opt/RFdiffusion/env/SE3Transformer && \
    pip install --no-cache-dir --no-deps /opt/RFdiffusion && \
    pip install --no-cache-dir e3nn pyrsistent hydra-core pynvml biopandas biopython pandas "dgl==1.1.3"

ENV DGLBACKEND="pytorch"

# Bake RFdiffusion model checkpoints (922 MB total, eliminates runtime S3 fetch)
ARG AWS_ACCESS_KEY_ID
ARG AWS_SECRET_ACCESS_KEY
ARG AWS_DEFAULT_REGION=us-west-2
RUN pip install --no-cache-dir awscli && \
    mkdir -p /opt/rfdiffusion/models && \
    aws s3 cp s3://endure-design-outputs/reference-models/rfdiffusion/Base_ckpt.pt /opt/rfdiffusion/models/Base_ckpt.pt && \
    aws s3 cp s3://endure-design-outputs/reference-models/rfdiffusion/Complex_base_ckpt.pt /opt/rfdiffusion/models/Complex_base_ckpt.pt

# Bake OVO bin scripts into container
COPY bin/validate_input.py /usr/local/bin/validate_input.py
COPY bin/standardize_pdb.py /usr/local/bin/standardize_pdb.py
RUN chmod +x /usr/local/bin/validate_input.py /usr/local/bin/standardize_pdb.py

# Install RunPod + boto3
RUN pip install --no-cache-dir runpod boto3

# Copy handler
COPY handler.py /opt/handler.py

ENTRYPOINT []
CMD ["python", "-u", "/opt/handler.py"]
