# ovo-colabdesign:v15 — AlphaFold2 initial guess (ColabDesign) + BindCraft for RunPod Serverless
# AF2 weights baked in for fast cold starts (~5.2 GB tar → ~15 GB extracted)
#
# All pip packages are installed into the conda Python so handler.py and
# the af2 eval subprocess share a single environment.

FROM nvcr.io/nvidia/jax:24.04-py3

# Nextflow/RunPod requires ps (procps)
RUN apt-get update && apt-get install -y --no-install-recommends procps && \
    rm -rf /var/lib/apt/lists/*

# Install conda (needed for PyRosetta from conda.graylab.jhu.edu)
# Pin Python 3.12 to avoid surprise upgrades (3.14 breaks runpod multiprocessing)
RUN curl -sL https://repo.anaconda.com/miniconda/Miniconda3-py312_24.11.1-0-Linux-x86_64.sh -o /tmp/miniconda.sh && \
    bash /tmp/miniconda.sh -b -p /opt/conda && \
    rm /tmp/miniconda.sh
ENV PATH="/opt/conda/bin:$PATH"

# Pin Python 3.12 so PyRosetta can't drag in 3.14
RUN conda install -y python=3.12 && conda clean -afy

# Install PyRosetta via conda (academic/free channel)
RUN conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main && \
    conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r && \
    conda install -y -c https://conda.graylab.jhu.edu pyrosetta && \
    conda clean -afy && \
    find /opt/conda -uid 995210 -exec chown root:root {} + 2>/dev/null || true

# Install ColabDesign + all pip dependencies into conda's Python
# (must come AFTER conda setup so pip resolves to /opt/conda/bin/pip)
RUN pip install --no-cache-dir \
    git+https://github.com/sokrypton/ColabDesign.git \
    biopython \
    numpy \
    "dm-haiku==0.0.12" \
    jax jaxlib

# Install additional BindCraft dependencies
RUN pip install --no-cache-dir seaborn pdbfixer

# Bake AlphaFold2 model params (5.2 GB tar, ~15 GB extracted)
ARG AWS_ACCESS_KEY_ID
ARG AWS_SECRET_ACCESS_KEY
ARG AWS_DEFAULT_REGION=us-west-2
RUN pip install --no-cache-dir awscli && \
    mkdir -p /opt/alphafold/params && \
    aws s3 cp s3://endure-design-outputs/reference-models/alphafold/alphafold_params_2022-12-06.tar /tmp/af2_params.tar && \
    tar -xf /tmp/af2_params.tar -C /opt/alphafold/params && \
    rm /tmp/af2_params.tar

# Bake OVO bin scripts into container
COPY bin/af2_initial_guess_scaffold_eval.py /usr/local/bin/af2_initial_guess_scaffold_eval.py
COPY bin/af2_initial_guess_binder_eval.py /usr/local/bin/af2_initial_guess_binder_eval.py
RUN chmod +x /usr/local/bin/af2_initial_guess_scaffold_eval.py /usr/local/bin/af2_initial_guess_binder_eval.py

# Copy BindCraft into container
COPY bindcraft/ /opt/bindcraft/
RUN chmod +x /opt/bindcraft/functions/DAlphaBall.gcc /opt/bindcraft/functions/dssp 2>/dev/null || true

# Install RunPod + boto3
RUN pip install --no-cache-dir runpod boto3

# Fix UID 995210 files from PyRosetta — RunPod's user-namespace runtime
# cannot map this UID, causing "container ID 995210 cannot be mapped to
# a host ID" on pull. Must be a separate final RUN so the layer diff
# records the ownership change.
RUN find / -uid 995210 -exec chown root:root {} + 2>/dev/null || true

# Copy handler
COPY handler.py /opt/handler.py

ENTRYPOINT []
CMD ["python", "-u", "/opt/handler.py"]
