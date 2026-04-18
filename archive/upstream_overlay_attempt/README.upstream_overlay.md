# wan_comfyui_template

この repo は `Hearmeman24/comfyui-wan` を固定 commit で build 時に取り込み、その上に `overrides/` の差分だけを重ねる構成です。

基準 upstream:

- repo: `https://github.com/Hearmeman24/comfyui-wan`
- commit: `8fadd7b70245a4437654d5af0017e4e9eca83fa9`
- subject: `fix: Add --enable-cors-header to ComfyUI launch args`

## 使い方

通常は `Dockerfile` をそのまま build します。build すると upstream の構成で image を作り、`overrides/comfyui-wan/` 配下のファイルだけが `/comfyui-wan/` に上書きされます。

変更の入れ方:

- workflow を変えたい: `overrides/comfyui-wan/workflows/...`
- 起動スクリプトを変えたい: `overrides/comfyui-wan/src/start.sh`
- upstream root のファイルを変えたい: `overrides/comfyui-wan/<path>`
- base image や build 時の node 追加みたいな image-layer 変更は root `Dockerfile` を直接変える

この構成では、元の repo に無い独自 manifest / preset / downloader 経路は active では使いません。まず upstream と同じ起動経路を維持し、その上で必要なファイルだけ差し替えます。

## アーカイブ

旧 manifest ベース構成は `archive/legacy_manifest_template/` に退避しています。

含まれるもの:

- 旧 `start.sh`
- 旧 `config/`
- 旧 `scripts/`
- 旧 `template_workflows/`
- 旧 `reports/`
- 旧 root workflow copy
- 旧 `Dockerfile` の控え
- 旧 `README` の控え

## Build

GitHub Actions の build workflow は引き続き `.github/workflows/build-ghcr.yml` を使います。
