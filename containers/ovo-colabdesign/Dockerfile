# ovo-colabdesign:v19 — AlphaFold2 initial guess (ColabDesign) + BindCraft for RunPod Serverless
# AF2 weights baked in for fast cold starts (~5.2 GB tar → ~15 GB extracted)
#
# Single Python stack: base image Python 3.10 with NVIDIA's pre-matched
# JAX 0.4.26 + CUDA 12.4 + cuDNN 9.1. No conda. PyRosetta via pip wheel.
#
# HIGH-UID FIX: tar --no-same-owner prevents AF2 weights tarball from
# preserving high UIDs when extracted as root.

FROM nvcr.io/nvidia/jax:24.04-py3

# Prevent tar from preserving high UIDs when extracting as root (build-only)
ENV TAR_OPTIONS=--no-same-owner

# Nextflow/RunPod requires ps (procps)
RUN apt-get update && apt-get install -y --no-install-recommends procps && \
    rm -rf /var/lib/apt/lists/*

# Pin JAX/jaxlib to what NVIDIA shipped — no pip install may upgrade them
RUN printf 'jax==0.4.26\njaxlib==0.4.26\nnumpy<2\n' > /opt/constraints.txt
ENV PIP_CONSTRAINT=/opt/constraints.txt

# Install ColabDesign + dependencies into base Python 3.10
RUN pip install --no-cache-dir \
    git+https://github.com/sokrypton/ColabDesign.git \
    biopython \
    numpy \
    "dm-haiku==0.0.12"

# Install PyRosetta via pip wheel (no conda needed)
RUN pip install --no-cache-dir pyrosetta-installer && \
    python3 -c "import pyrosetta_installer; pyrosetta_installer.install_pyrosetta()"

# Install handler + BindCraft dependencies
RUN pip install --no-cache-dir runpod boto3 seaborn scipy matplotlib pandas

# pdbfixer needs openmm
RUN pip install --no-cache-dir openmm pdbfixer

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

# Install RunPod (last, so constraint still applies)
# Note: runpod is already installed above, this is a no-op but explicit
COPY handler.py /opt/handler.py

# Build-time assertions
RUN python3 -c "\
import jax, jaxlib, numpy; \
assert jax.__version__.startswith('0.4.26'), f'Expected jax 0.4.26, got {jax.__version__}'; \
assert 'dist-packages' in jaxlib.__file__, f'jaxlib not from NVIDIA dist-packages: {jaxlib.__file__}'; \
assert numpy.__version__.startswith('1.'), f'numpy 2.x breaks jax 0.4.26: got {numpy.__version__}'; \
import haiku; import jax.interpreters.xla as x; \
assert hasattr(x, 'xe'), f'jax.interpreters.xla.xe missing'; \
from colabdesign import mk_af_model; \
import pyrosetta; \
import pdbfixer; \
print(f'JAX {jax.__version__} (NVIDIA), numpy {numpy.__version__}, haiku OK, ColabDesign OK, PyRosetta OK, pdbfixer OK'); \
"
# Merged-filesystem sanity check
RUN bad=$(find / -xdev \( -uid +65535 -o -gid +65535 \) 2>/dev/null | head -20); \
    [ -z "$bad" ] || { echo "HIGH UID/GID FILES FOUND:"; echo "$bad"; exit 1; }

# Clear build-only env vars
ENV TAR_OPTIONS=
ENV PIP_CONSTRAINT=

ENTRYPOINT []
CMD ["python3", "-u", "/opt/handler.py"]
