# ovo-colabdesign:v17 — AlphaFold2 initial guess (ColabDesign) + BindCraft for RunPod Serverless
# AF2 weights baked in for fast cold starts (~5.2 GB tar → ~15 GB extracted)
#
# All pip packages are installed into the conda Python so handler.py and
# the af2 eval subprocess share a single environment.
#
# HIGH-UID FIX: Three things cause pull failures on RunPod (user namespaces
# reject UID/GID >65535):
#   1. tar as root preserves original ownership (--same-owner default) —
#      the AF2 weights tarball may contain high-UID files
#   2. chown without -h follows symlinks — conda trees are mostly symlinks,
#      so the symlinks themselves keep the offending UID
#   3. find -uid misses files where only the GID is high

FROM nvcr.io/nvidia/jax:24.04-py3

# Prevent tar from preserving high UIDs when extracting as root (build-only)
ENV TAR_OPTIONS=--no-same-owner

# Nextflow/RunPod requires ps (procps)
RUN apt-get update && apt-get install -y --no-install-recommends procps && \
    rm -rf /var/lib/apt/lists/*

# Install conda + pin Python 3.12 + PyRosetta + fix high UIDs/GIDs
# -xdev: stay on real filesystems, skip /proc /sys
RUN curl -sL https://repo.anaconda.com/miniconda/Miniconda3-py312_24.11.1-0-Linux-x86_64.sh -o /tmp/miniconda.sh && \
    bash /tmp/miniconda.sh -b -p /opt/conda && \
    rm /tmp/miniconda.sh && \
    export PATH="/opt/conda/bin:$PATH" && \
    conda install -y python=3.12 && \
    conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main && \
    conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r && \
    conda install -y -c https://conda.graylab.jhu.edu pyrosetta && \
    conda clean -afy && \
    find / -xdev \( -uid 995210 -o -gid 995210 \) -exec chown -h root:root {} + 2>/dev/null || true
ENV PATH="/opt/conda/bin:$PATH"

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
    tar --no-same-owner -xf /tmp/af2_params.tar -C /opt/alphafold/params && \
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

# Copy handler
COPY handler.py /opt/handler.py

# Merged-filesystem sanity check (necessary but not sufficient — layers are
# validated independently at pull time). The sufficient check is docker save +
# per-layer tar inspection, run post-build before push.
RUN bad=$(find / -xdev \( -uid +65535 -o -gid +65535 \) 2>/dev/null | head -20); \
    [ -z "$bad" ] || { echo "HIGH UID/GID FILES FOUND:"; echo "$bad"; exit 1; }

# Clear TAR_OPTIONS so runtime tar behaves normally
ENV TAR_OPTIONS=

ENTRYPOINT []
CMD ["python", "-u", "/opt/handler.py"]
