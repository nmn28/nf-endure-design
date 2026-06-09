# ovo-colabdesign:v2 — AlphaFold2 initial guess (ColabDesign) for RunPod Serverless
# AF2 weights baked in for fast cold starts (~5.2 GB tar → ~15 GB extracted)

FROM nvcr.io/nvidia/jax:24.04-py3

# Nextflow/RunPod requires ps (procps)
RUN apt-get update && apt-get install -y --no-install-recommends procps && \
    rm -rf /var/lib/apt/lists/*

# Install ColabDesign + dependencies
RUN pip install --no-cache-dir \
    git+https://github.com/sokrypton/ColabDesign.git \
    biopython \
    numpy \
    "dm-haiku==0.0.12"

# Bake AlphaFold2 model params (5.2 GB tar, ~15 GB extracted)
ARG AWS_ACCESS_KEY_ID
ARG AWS_SECRET_ACCESS_KEY
ARG AWS_DEFAULT_REGION=us-west-2
RUN pip install --no-cache-dir awscli && \
    mkdir -p /opt/alphafold/params && \
    aws s3 cp s3://endure-design-outputs/reference-models/alphafold/alphafold_params_2022-12-06.tar /tmp/af2_params.tar && \
    tar -xf /tmp/af2_params.tar -C /opt/alphafold/params && \
    rm /tmp/af2_params.tar

# Fix high-UID files that break RunPod's user namespace mapping
RUN find / -uid 995210 -exec chown root:root {} + 2>/dev/null || true

# Bake OVO bin scripts into container
COPY bin/af2_initial_guess_scaffold_eval.py /usr/local/bin/af2_initial_guess_scaffold_eval.py
COPY bin/af2_initial_guess_binder_eval.py /usr/local/bin/af2_initial_guess_binder_eval.py
RUN chmod +x /usr/local/bin/af2_initial_guess_scaffold_eval.py /usr/local/bin/af2_initial_guess_binder_eval.py

# Install RunPod + boto3
RUN pip install --no-cache-dir runpod boto3

# Copy handler
COPY handler.py /opt/handler.py

ENTRYPOINT []
CMD ["python", "-u", "/opt/handler.py"]
