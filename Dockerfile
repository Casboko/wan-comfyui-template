FROM runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404

ARG COMFYUI_REF=3086026401180c9216bcb6ace442a4e3587d2c66

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

RUN git init /opt/ComfyUI && \
    cd /opt/ComfyUI && \
    git remote add origin https://github.com/comfyanonymous/ComfyUI && \
    git fetch --depth 1 origin "${COMFYUI_REF}" && \
    git checkout --detach FETCH_HEAD

RUN python3 - <<'PY' > /tmp/comfyui-core-requirements.txt
from pathlib import Path
req = Path("/opt/ComfyUI/requirements.txt").read_text().splitlines()
for line in req:
    s = line.strip()
    if not s:
        continue
    if s.startswith("#"):
        print(line)
        continue
    name = s.split("==")[0].split(">=")[0].split("~=")[0]
    if name in {"torch", "torchvision", "torchaudio"}:
        continue
    print(line)
PY

RUN pip install -r /tmp/comfyui-core-requirements.txt && rm -f /tmp/comfyui-core-requirements.txt

COPY scripts/ /opt/template-scripts/
COPY config/ /opt/template-config/
COPY template_workflows/ /opt/template-workflows/
COPY start.sh /start.sh

RUN chmod +x /start.sh /opt/template-scripts/template_downloader.py /opt/template-scripts/workflow_dependency_report.py

CMD ["/start.sh"]
