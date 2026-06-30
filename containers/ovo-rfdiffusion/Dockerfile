# ovo-rfdiffusion:v3 — RFdiffusion v1/v2 + RFdiffusion3 for RunPod Serverless
# Weights baked in for fast cold starts

FROM nvcr.io/nvidia/pytorch:24.12-py3

# Nextflow/RunPod requires ps (procps)
RUN apt-get update && apt-get install -y --no-install-recommends procps && \
    rm -rf /var/lib/apt/lists/*

# Install RFdiffusion v1/v2 (SE3Transformer must be installed from bundled env/ first)
RUN git clone --depth 1 https://github.com/RosettaCommons/RFdiffusion.git /opt/RFdiffusion && \
    pip install --no-cache-dir /opt/RFdiffusion/env/SE3Transformer && \
    pip install --no-cache-dir --no-deps /opt/RFdiffusion && \
    pip install --no-cache-dir e3nn pyrsistent hydra-core pynvml biopandas biopython pandas && \
    pip install --no-cache-dir dgl -f https://data.dgl.ai/wheels/torch-2.5/cu124/repo.html

ENV DGLBACKEND="pytorch"

# Install RFdiffusion3 via rc-foundry
RUN pip install --no-cache-dir "rc-foundry[all]" gemmi

# Bake model checkpoints (RFdiffusion v1/v2 + RFdiffusion3)
ARG AWS_ACCESS_KEY_ID
ARG AWS_SECRET_ACCESS_KEY
ARG AWS_DEFAULT_REGION=us-west-2
RUN pip install --no-cache-dir awscli && \
    mkdir -p /opt/rfdiffusion/models /opt/rfdiffusion3/models && \
    aws s3 cp s3://endure-design-outputs/reference-models/rfdiffusion/Base_ckpt.pt /opt/rfdiffusion/models/Base_ckpt.pt && \
    aws s3 cp s3://endure-design-outputs/reference-models/rfdiffusion/Complex_base_ckpt.pt /opt/rfdiffusion/models/Complex_base_ckpt.pt && \
    aws s3 cp s3://endure-design-outputs/reference-models/rfdiffusion3/rfd3_latest.ckpt /opt/rfdiffusion3/models/rfd3_latest.ckpt || \
    echo "WARNING: rfd3_latest.ckpt not found in S3 — will need to be uploaded before v3 mode works"

# Bake OVO bin scripts into container
COPY bin/validate_input.py /usr/local/bin/validate_input.py
COPY bin/standardize_pdb.py /usr/local/bin/standardize_pdb.py
COPY bin/build_input_json.py /usr/local/bin/build_input_json.py
COPY bin/standardize_cif.py /usr/local/bin/standardize_cif.py
RUN chmod +x /usr/local/bin/validate_input.py /usr/local/bin/standardize_pdb.py \
    /usr/local/bin/build_input_json.py /usr/local/bin/standardize_cif.py

# Install RunPod + boto3
RUN pip install --no-cache-dir runpod boto3

# Copy handler
COPY handler.py /opt/handler.py

ENTRYPOINT []
CMD ["python", "-u", "/opt/handler.py"]
