FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu24.04 AS base

ARG UPSTREAM_REPO=https://github.com/Hearmeman24/comfyui-wan.git
ARG UPSTREAM_REF=8fadd7b70245a4437654d5af0017e4e9eca83fa9
ARG SAGEATTENTION_REF=68de3797d163b89d28f9a38026c3b7313f6940d2

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_PREFER_BINARY=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    CMAKE_BUILD_PARALLEL_LEVEL=8 \
    PATH="/opt/venv/bin:$PATH"

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv python3.12-dev \
        python3-pip \
        curl ffmpeg ninja-build git aria2 git-lfs wget vim \
        libgl1 libglib2.0-0 build-essential gcc g++ \
        libgoogle-perftools4 ca-certificates && \
    ln -sf /usr/bin/python3.12 /usr/bin/python && \
    ln -sf /usr/bin/pip3 /usr/bin/pip && \
    python3.12 -m venv /opt/venv && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --pre torch torchvision torchaudio \
        --index-url https://download.pytorch.org/whl/nightly/cu128

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install packaging setuptools wheel

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install \
        comfy-cli \
        jupyterlab jupyterlab-lsp \
        jupyter-server jupyter-server-terminals \
        ipykernel jupyterlab_code_formatter \
        requests huggingface_hub pyyaml gdown triton

RUN --mount=type=cache,target=/root/.cache/pip \
    /usr/bin/yes | comfy --workspace /ComfyUI install

RUN git clone "${UPSTREAM_REPO}" /comfyui-wan && \
    git -C /comfyui-wan fetch --depth 1 origin "${UPSTREAM_REF}" && \
    git -C /comfyui-wan checkout --detach FETCH_HEAD

COPY config/ /opt/template-config/
COPY scripts/ /opt/template-scripts/
COPY template_workflows/ /opt/template-workflows/
COPY overrides/ /opt/overrides/

RUN python3 - <<'PY'
import json
import pathlib
import subprocess

manifest_path = pathlib.Path("/opt/template-config/manifests/custom_nodes.json")
cache_root = pathlib.Path("/opt/template-node-cache")
cache_root.mkdir(parents=True, exist_ok=True)

for item in json.loads(manifest_path.read_text()):
    if not item.get("enabled", True):
        continue
    dst = cache_root / item["name"]
    if dst.exists():
        continue
    subprocess.check_call(["git", "clone", "--depth", "1", item["repo"], str(dst)])
    subprocess.check_call(["git", "-C", str(dst), "fetch", "--depth", "1", "origin", item["ref"]])
    subprocess.check_call(["git", "-C", str(dst), "checkout", "--force", "FETCH_HEAD"])
PY

RUN git init /opt/SageAttention && \
    cd /opt/SageAttention && \
    git remote add origin https://github.com/thu-ml/SageAttention.git && \
    git fetch --depth 1 origin "${SAGEATTENTION_REF}" && \
    git checkout --detach FETCH_HEAD

RUN if [ -d /opt/overrides/comfyui-wan ]; then \
      cp -a /opt/overrides/comfyui-wan/. /comfyui-wan/; \
    fi && \
    test -f /comfyui-wan/src/start.sh

FROM base AS final

ENV PATH="/opt/venv/bin:$PATH" \
    TEMPLATE_PIP_CONSTRAINT="/opt/template-pip/constraints-cu128.txt"

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install opencv-python

RUN python3 - <<'PY'
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

packages = [
    "torch",
    "torchvision",
    "torchaudio",
    "triton",
    "numpy",
]

lines = ["# Generated at image build time from the active CUDA 12.8 runtime stack."]
for package in packages:
    try:
        lines.append(f"{package}=={version(package)}")
    except PackageNotFoundError:
        continue

target = Path("/opt/template-pip/constraints-cu128.txt")
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

RUN cp /comfyui-wan/4xLSDIR.pth /4xLSDIR.pth && \
    chmod +x /comfyui-wan/src/start.sh && \
    chmod +x /opt/template-scripts/template_downloader.py /opt/template-scripts/workflow_dependency_report.py /opt/template-scripts/preset_audit.py

CMD ["/bin/bash", "/comfyui-wan/src/start.sh"]
