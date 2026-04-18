# wan_comfyui_template

この repo の正は、`Hearmeman24/comfyui-wan` そのものではありません。

正とするのは、この repo にある manifest / preset です。

- 取得する custom node: [config/manifests/custom_nodes.json](/home/kenic/repositories/wan_comfyui_template/config/manifests/custom_nodes.json:1)
- 取得する weight / LoRA / model: [config/manifests/hf_models.json](/home/kenic/repositories/wan_comfyui_template/config/manifests/hf_models.json:1)
- どの group を有効にするか: [config/settings/workflow_bundle.env](/home/kenic/repositories/wan_comfyui_template/config/settings/workflow_bundle.env:1)

## Active 構成

- [Dockerfile](/home/kenic/repositories/wan_comfyui_template/Dockerfile:1)
  - `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404` をベースに使う
  - `config/`, `scripts/`, `template_workflows/`, `start.sh` を image に同梱する
  - custom node source は build 時に manifest から cache する
- [start.sh](/home/kenic/repositories/wan_comfyui_template/start.sh:1)
  - `/workspace` 上の ComfyUI を起動する
  - preset を読み、model download と node install を起動する
  - `INSTALL_SAGEATTENTION=1` のときだけ SageAttention を optional install する
- [scripts/template_downloader.py](/home/kenic/repositories/wan_comfyui_template/scripts/template_downloader.py:1)
  - `custom_nodes.json` と `hf_models.json` を読む
  - enabled group に入っているものだけ取得する
- [template_workflows/](/home/kenic/repositories/wan_comfyui_template/template_workflows)
  - 配布する workflow JSON

## Preset

デフォルトは [config/settings/workflow_bundle.env](/home/kenic/repositories/wan_comfyui_template/config/settings/workflow_bundle.env:1) です。

主な preset:

- [config/settings/workflow_bundle.env](/home/kenic/repositories/wan_comfyui_template/config/settings/workflow_bundle.env:1)
  - 標準 bundle
- [config/settings/runpod_48gb.env](/home/kenic/repositories/wan_comfyui_template/config/settings/runpod_48gb.env:1)
  - 48GB 向け
- [config/settings/runpod_80gb.env](/home/kenic/repositories/wan_comfyui_template/config/settings/runpod_80gb.env:1)
  - 80GB 向け
- [config/settings/minimal.env](/home/kenic/repositories/wan_comfyui_template/config/settings/minimal.env:1)
  - 最小構成
- [config/settings/research.env](/home/kenic/repositories/wan_comfyui_template/config/settings/research.env:1)
  - 候補群込み

RunPod で preset を差し替える場合は、`DOWNLOADER_SETTINGS_PATH=/workspace/template_settings.env` を渡します。

## Build

通常は root の `Dockerfile` をそのまま build します。

GitHub Actions build は [build-ghcr.yml](/home/kenic/repositories/wan_comfyui_template/.github/workflows/build-ghcr.yml:1) を使います。

## Archive

いま参照しないものは `archive/` に退避しています。

- [archive/legacy_manifest_template](/home/kenic/repositories/wan_comfyui_template/archive/legacy_manifest_template)
  - manifest 構成の保管用 snapshot
- [archive/upstream_overlay_attempt](/home/kenic/repositories/wan_comfyui_template/archive/upstream_overlay_attempt)
  - upstream overlay 方式の試行版
