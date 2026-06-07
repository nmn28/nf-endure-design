# ovo-rfdiffusion:v1 — RFDiffusion for OVO backbone design pipeline
# Vendored from OVO (Merck © 2025, MIT License)
# For AWS Batch execution via Seqera/Nextflow

FROM nvcr.io/nvidia/pytorch:24.07-py3

# Nextflow requires ps (procps)
RUN apt-get update && apt-get install -y --no-install-recommends procps && \
    rm -rf /var/lib/apt/lists/*

# Clone RFDiffusion
RUN git clone --depth 1 https://github.com/RosettaCommons/RFdiffusion.git /opt/RFdiffusion

# Install Python dependencies (matches OVO's rfdiffusion.yml)
RUN pip install --no-cache-dir \
    e3nn==0.3.3 \
    hydra-core==1.3.2 \
    pyrsistent==0.19.3 \
    pynvml==11.0.0 \
    decorator==5.1.0 \
    wandb==0.12.0 \
    numpy==1.26.4 \
    pandas==2.3.1 \
    biopandas==0.5.1

# DGL for PyTorch 2.4 + CUDA 12.4
RUN pip install --no-cache-dir dgl -f https://data.dgl.ai/wheels/torch-2.4/cu124/repo.html || \
    pip install --no-cache-dir dgl

# dllogger (NVIDIA)
RUN pip install --no-cache-dir git+https://github.com/NVIDIA/dllogger#egg=dllogger

# SE3Transformer + RFdiffusion package
RUN pip install --no-cache-dir /opt/RFdiffusion/env/SE3Transformer && \
    pip install --no-cache-dir --no-deps /opt/RFdiffusion

# Create models directory (weights loaded from S3 at runtime via Nextflow staging)
RUN mkdir -p /opt/RFdiffusion/models

ENV DGLBACKEND="pytorch"

# Bake OVO bin scripts into container (ENDURE-PATCH: replaces ${moduleDir}/bin/ pattern)
COPY bin/validate_input.py /usr/local/bin/validate_input.py
COPY bin/standardize_pdb.py /usr/local/bin/standardize_pdb.py
RUN chmod +x /usr/local/bin/validate_input.py /usr/local/bin/standardize_pdb.py

WORKDIR /workspace
