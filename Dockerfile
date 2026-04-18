FROM runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_PREFER_BINARY=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    CMAKE_BUILD_PARALLEL_LEVEL=8 \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      python3-venv python3-dev python3-pip \
      curl ffmpeg ninja-build git git-lfs aria2 wget vim \
      libgl1 libglib2.0-0 build-essential gcc g++ \
      libgoogle-perftools4 ca-certificates && \
    python3 -m venv --system-site-packages /opt/venv && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip setuptools wheel packaging
RUN pip install \
      comfy-cli \
      jupyterlab jupyterlab-lsp \
      jupyter-server jupyter-server-terminals \
      ipykernel jupyterlab_code_formatter \
      requests huggingface_hub pyyaml gdown

RUN bash -lc 'set +o pipefail; /usr/bin/yes | comfy --workspace /ComfyUI install'

COPY scripts/ /opt/template-scripts/
COPY config/ /opt/template-config/
COPY template_workflows/ /opt/template-workflows/
COPY start.sh /start.sh

RUN chmod +x /start.sh /opt/template-scripts/template_downloader.py /opt/template-scripts/workflow_dependency_report.py

CMD ["/start.sh"]
