# wan_comfyui_template

この repo は、`Hearmeman24/comfyui-wan` の実行基盤を土台に維持したまま、外部リソース取得だけを自分用に差し替えるための overlay です。

設計判断の基準は [docs/upstream-resource-layer.md](docs/upstream-resource-layer.md) を優先してください。

## Active 構成

- [Dockerfile](/home/kenic/repositories/wan_comfyui_template/Dockerfile:1)
  - `nvidia/cuda:12.8.1-cudnn-devel-ubuntu24.04` をベースに使う
  - upstream `Hearmeman24/comfyui-wan` を fixed commit で checkout する
  - `config/`, `scripts/`, `template_workflows/`, `overrides/` を image に同梱する
  - `config/manifests/custom_nodes.json` から custom node source を build 時 cache する
  - build 済み runtime から `torch` / `torchvision` / `torchaudio` / `triton` / `numpy` の constraints を生成する
- [overrides/comfyui-wan/src/start.sh](/home/kenic/repositories/wan_comfyui_template/overrides/comfyui-wan/src/start.sh:1)
  - upstream 側 `src/start.sh` を overlay で置き換える
  - preset を読み、model download と node install を起動する
  - `/ComfyUI` を workspace へ seed して起動する
  - bundled node cache も enabled node group だけ workspace へ seed する
  - `INSTALL_SAGEATTENTION=1` のときだけ SageAttention を optional install する
- [scripts/template_downloader.py](/home/kenic/repositories/wan_comfyui_template/scripts/template_downloader.py:1)
  - `custom_nodes.json` と `hf_models.json` を読む
  - enabled group に入っているものだけ取得する
  - node install 時に pip constraints を適用する
  - locked runtime package を requirements から除外する

## この repo で管理する正

- 取得する custom node: [config/manifests/custom_nodes.json](/home/kenic/repositories/wan_comfyui_template/config/manifests/custom_nodes.json:1)
- 取得する weight / LoRA / model: [config/manifests/hf_models.json](/home/kenic/repositories/wan_comfyui_template/config/manifests/hf_models.json:1)
- どの group を有効にするか: [config/settings/workflow_bundle.env](/home/kenic/repositories/wan_comfyui_template/config/settings/workflow_bundle.env:1)
- 配布する workflow: [template_workflows/](/home/kenic/repositories/wan_comfyui_template/template_workflows)
- upstream へ重ねる差分: [overrides/comfyui-wan/](/home/kenic/repositories/wan_comfyui_template/overrides/comfyui-wan)

## Preset

デフォルト preset は [config/settings/workflow_bundle.env](/home/kenic/repositories/wan_comfyui_template/config/settings/workflow_bundle.env:1) です。

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

RunPod で preset を差し替える場合は `DOWNLOADER_SETTINGS_PATH=/workspace/template_settings.env` を渡します。

## Build / Runtime

通常は root の `Dockerfile` をそのまま build します。

起動時の主な流れ:

1. image 内 `/comfyui-wan` と `/ComfyUI` を upstream fixed commit から用意する
2. overlay 側 `start.sh` が preset を読む
3. `/ComfyUI` を workspace 側 `COMFYUI_BASE` へ seed する
4. bundled node cache を workspace へ展開する
5. `template_downloader.py` が models / nodes を manifest に従って同期する
6. ComfyUI を workspace から起動する

GitHub Actions build は [build-ghcr.yml](/home/kenic/repositories/wan_comfyui_template/.github/workflows/build-ghcr.yml:1) を使います。

## 安全策

この repo では custom node install で runtime を壊さないことを重視します。

- `torch` / `torchvision` / `torchaudio` / `triton` / `numpy` の constraints を image build 時に生成する
- `template_downloader.py` から呼ぶ pip install に constraints を適用する
- locked runtime package は node 側 `requirements.txt` から除外する
- `install.py` 実行時も `PYTHONPATH` と constraints を引き継ぐ

## Archive

参照用 snapshot は `archive/` に残しています。

- [archive/legacy_manifest_template](/home/kenic/repositories/wan_comfyui_template/archive/legacy_manifest_template)
  - 旧 manifest-first 構成
- [archive/upstream_overlay_attempt](/home/kenic/repositories/wan_comfyui_template/archive/upstream_overlay_attempt)
  - overlay 方式の初期試行
