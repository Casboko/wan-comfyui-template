#!/usr/bin/env bash
set -euo pipefail

TEMPLATE_CONFIG_ROOT="/opt/template-config"
TEMPLATE_SCRIPT_ROOT="/opt/template-scripts"
TEMPLATE_WORKFLOW_ROOT="/opt/template-workflows"
NETWORK_VOLUME="${NETWORK_VOLUME:-/workspace}"
COMFYUI_DIR="${COMFYUI_BASE:-$NETWORK_VOLUME/ComfyUI}"
WORKFLOW_DIR="${COMFYUI_DIR}/user/default/workflows"
JUPYTER_DIR="${NETWORK_VOLUME}"
RUNPOD_POD_ID="${RUNPOD_POD_ID:-local}"
COMFY_LOG="${NETWORK_VOLUME}/comfyui_${RUNPOD_POD_ID}_nohup.log"
MODEL_LOG="${NETWORK_VOLUME}/template_model_download_${RUNPOD_POD_ID}.log"
SETTINGS_OVERRIDE="${DOWNLOADER_SETTINGS_PATH:-$NETWORK_VOLUME/template_settings.env}"
DEFAULT_SETTINGS="${TEMPLATE_PRESET_PATH:-$TEMPLATE_CONFIG_ROOT/settings/workflow_bundle.env}"
START_JUPYTER="${START_JUPYTER:-1}"
INSTALL_SAGEATTENTION="${INSTALL_SAGEATTENTION:-0}"
COMFYUI_URL="${COMFYUI_URL:-http://127.0.0.1:8188}"

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

log() {
  printf '[template] %s\n' "$*"
}

ensure_packages() {
  local missing=()
  command_exists aria2c || missing+=(aria2)
  command_exists curl || missing+=(curl)
  command_exists git || missing+=(git)
  if [ ${#missing[@]} -gt 0 ]; then
    log "Installing runtime packages: ${missing[*]}"
    apt-get update
    apt-get install -y "${missing[@]}"
  fi
}

maybe_preload_tcmalloc() {
  local tcmalloc
  tcmalloc="$(ldconfig -p | grep -Po 'libtcmalloc\.so\.\d+' | head -n 1 || true)"
  if [ -n "${tcmalloc:-}" ]; then
    export LD_PRELOAD="$tcmalloc"
  fi
}

resolve_settings() {
  if [ -f "$SETTINGS_OVERRIDE" ]; then
    export DOWNLOADER_SETTINGS_PATH="$SETTINGS_OVERRIDE"
  else
    export DOWNLOADER_SETTINGS_PATH="$DEFAULT_SETTINGS"
  fi
  log "Using settings file: $DOWNLOADER_SETTINGS_PATH"
}

load_settings_env() {
  if [ ! -f "$DOWNLOADER_SETTINGS_PATH" ]; then
    return
  fi
  set -a
  # shellcheck disable=SC1090
  . "$DOWNLOADER_SETTINGS_PATH"
  set +a
  log "Loaded template settings into shell environment"
}

run_additional_params() {
  if [ -f "$NETWORK_VOLUME/additional_params.sh" ]; then
    chmod +x "$NETWORK_VOLUME/additional_params.sh"
    log "Running additional_params.sh"
    "$NETWORK_VOLUME/additional_params.sh"
  fi
}

ensure_workspace_layout() {
  mkdir -p "$NETWORK_VOLUME"
  ensure_comfyui_workspace
  mkdir -p "$WORKFLOW_DIR"
}

ensure_comfyui_workspace() {
  if [ -f "$COMFYUI_DIR/main.py" ]; then
    return
  fi
  log "ComfyUI workspace not found, installing into ${COMFYUI_DIR}"
  rm -rf "$COMFYUI_DIR"
  bash -lc 'comfy --skip-prompt --no-enable-telemetry --workspace "$1" install --nvidia --skip-manager --skip-torch-or-directml' _ "$COMFYUI_DIR"
}

copy_template_workflows() {
  mkdir -p "$WORKFLOW_DIR"
  find "$TEMPLATE_WORKFLOW_ROOT" -maxdepth 1 -type f -name '*.json' -print0 | while IFS= read -r -d '' src; do
    local name
    local dst
    name="$(basename "$src")"
    if [ -n "${TEMPLATE_WORKFLOW_INCLUDE:-}" ]; then
      local include
      local matched=0
      IFS=',' read -r -a includes <<< "$TEMPLATE_WORKFLOW_INCLUDE"
      for include in "${includes[@]}"; do
        include="${include#"${include%%[![:space:]]*}"}"
        include="${include%"${include##*[![:space:]]}"}"
        if [ "$include" = "$name" ]; then
          matched=1
          break
        fi
      done
      if [ "$matched" -ne 1 ]; then
        continue
      fi
    fi
    dst="${WORKFLOW_DIR}/${name}"
    if [ ! -f "$dst" ]; then
      cp "$src" "$dst"
      log "Copied workflow: ${name}"
    fi
  done
}

start_jupyter_if_enabled() {
  if [ "$START_JUPYTER" != "1" ]; then
    return
  fi
  if command_exists jupyter-lab; then
    nohup jupyter-lab --ip=0.0.0.0 --allow-root --no-browser --NotebookApp.token='' --NotebookApp.password='' --ServerApp.allow_origin='*' --ServerApp.allow_credentials=True --notebook-dir="$JUPYTER_DIR" >"$NETWORK_VOLUME/jupyter_${RUNPOD_POD_ID}.log" 2>&1 &
    log "JupyterLab started"
  fi
}

install_sageattention_if_enabled() {
  if [ "$INSTALL_SAGEATTENTION" != "1" ]; then
    return
  fi
  log "Installing SageAttention"
  rm -rf /tmp/SageAttention
  git clone https://github.com/thu-ml/SageAttention.git /tmp/SageAttention
  (
    cd /tmp/SageAttention
    git reset --hard 68de379
    export EXT_PARALLEL=4 NVCC_APPEND_FLAGS="--threads 8" MAX_JOBS=32
    python3 -m pip install -e .
  )
  export COMFYUI_EXTRA_ARGS="${COMFYUI_EXTRA_ARGS:-} --use-sage-attention"
}

run_node_phase() {
  log "Installing custom nodes"
  python3 "$TEMPLATE_SCRIPT_ROOT/template_downloader.py" --phase nodes
}

start_model_phase() {
  log "Starting background model download"
  nohup python3 "$TEMPLATE_SCRIPT_ROOT/template_downloader.py" --phase models >"$MODEL_LOG" 2>&1 &
  export TEMPLATE_MODEL_PID=$!
}

start_comfyui() {
  local -a args
  args=(python3 "$COMFYUI_DIR/main.py" --listen 0.0.0.0 --port 8188 --enable-cors-header '*')
  if [ -n "${COMFYUI_EXTRA_ARGS:-}" ]; then
    # shellcheck disable=SC2206
    local extra=( ${COMFYUI_EXTRA_ARGS} )
    args+=("${extra[@]}")
  fi
  nohup "${args[@]}" >"$COMFY_LOG" 2>&1 &
}

wait_for_comfyui() {
  local waited=0
  local max_wait=120
  until curl --silent --fail "$COMFYUI_URL" --output /dev/null; do
    if [ "$waited" -ge "$max_wait" ]; then
      log "ComfyUI did not become ready within ${max_wait}s"
      log "Startup log: $COMFY_LOG"
      return 1
    fi
    log "Waiting for ComfyUI... ($waited/${max_wait}s)"
    sleep 2
    waited=$((waited + 2))
  done
  log "ComfyUI is ready"
}

main() {
  maybe_preload_tcmalloc
  ensure_packages
  resolve_settings
  load_settings_env
  run_additional_params
  ensure_workspace_layout
  copy_template_workflows
  start_jupyter_if_enabled
  start_model_phase
  run_node_phase
  install_sageattention_if_enabled
  start_comfyui
  wait_for_comfyui
  log "ComfyUI log: $COMFY_LOG"
  log "Model download log: $MODEL_LOG"
  sleep infinity
}

main "$@"
