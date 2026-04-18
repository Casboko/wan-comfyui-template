# wan_comfyui_template

Hearmeman 系テンプレートの骨格だけ借りて、起動時に必要なものだけを入れる前提で組み替えた作業用ベースです。

## 今入っているもの

- `start.sh`
  - Network Volume 前提の起動骨格
  - custom node 導入と model download を分離
  - model download はバックグラウンド化
- `scripts/template_downloader.py`
  - manifest 駆動
  - Hugging Face 並列 download
  - custom node install
  - CivitAI version ID / queue file download
- `scripts/workflow_dependency_report.py`
  - ローカル workflow JSON から node pack / model filename / 埋め込み URL を抽出
- `config/manifests/custom_nodes.json`
  - 4本の workflow から判明した node pack の初期 manifest
- `config/manifests/hf_models.json`
  - 現時点で確度の高い HF weights の初期 manifest
- `config/settings/*.env`
  - `minimal`
  - `workflow_bundle`
  - `research`
  - `runpod_48gb`
  - `runpod_80gb`
  - preset ごとに node / model / 配布 workflow を切り替え

## 使い方

デフォルトは `config/settings/workflow_bundle.env` です。RunPod 側で `DOWNLOADER_SETTINGS_PATH=/workspace/template_settings.env` を渡すと、Volume 上の設定で上書きできます。

VRAM 別の初期プリセット:

- `config/settings/runpod_48gb.env`
  - `obsxrver/wan2.2-i2v-lightx2v-260412` の FP8 merged pair を主系統に使用
  - 専用 workflow `*FP8 260412.json` を配布
- `config/settings/runpod_80gb.env`
  - official 28.6GB fp16 pair + `260412` Lightx2v LoRA を主系統に使用
  - text encoder は FP8/BF16 両対応

現在の active preset では、以下を意図的に除外しています。

- `WAN 2.2 I2V.json`
- Lynx 系 weights

一方で、`SVI pro.json` の現行 active path に合わせて、以下は active preset に含めています。

- official `wan2.2_i2v_high_noise_14B_fp16.safetensors`
- official `wan2.2_i2v_low_noise_14B_fp16.safetensors`
- `SVI_v2_PRO_Wan2.2-I2V-A14B_HIGH/LOW...`
- `260412` Lightx2v I2V LoRA pair

デフォルト preset (`workflow_bundle`) では、以下の追加 node も入ります。

- `ComfyUI-WanVideoWrapper`
- `cg-use-everywhere`
- `ComfyUI-Chibi-Nodes`
- `ComfyUI_essentials`
- `ComfyUI-mxToolkit`
- `comfyui-dream-video-batches`
- `CRT-Nodes`
- `ComfyUI-Image-Filters`
- `ComfyUI-WanSeamlessFlow`

`lightx2v_compat` は `obsxrver/wan2.2-i2v-lightx2v-260412` の `260412` LoRA pair を指します。旧 Kijai / Wan2.1 fallback 群は `research` preset 側へ隔離しています。

加えて、Kijai の `LoRAs/Wan22_Lightx2v` にある `260412` 系 LoRA 4本も、`workflow_bundle / runpod_48gb / runpod_80gb / research` で取得対象にしています。

- `Wan_2_2_I2V_A14B_HIGH_lightx2v_4step_lora_260412_rank_64_fp16.safetensors`
- `Wan_2_2_I2V_A14B_LOW_lightx2v_4step_lora_260412_rank_64_fp16.safetensors`
- `Wan_2_2_I2V_A14B_HIGH_lightx2v_4step_lora_260412_rank_256_fp16.safetensors`
- `Wan_2_2_I2V_A14B_LOW_lightx2v_4step_lora_260412_rank_256_fp16.safetensors`

さらに、`workflow_bundle / runpod_48gb / runpod_80gb / research` では CivitAI の default LoRA pack 35組 70本も初期取得します。queue file は [config/civitai_queues/runpod_default_loras.json](/home/kenic/repositories/wan_comfyui_template/config/civitai_queues/runpod_default_loras.json:1) です。

- 配置先は `models/loras/runpod_default/<category>/`
- ファイル名は CivitAI 元名ではなく、`<slug>-high.safetensors` / `<slug>-low.safetensors` に正規化
- `minimal` preset だけはこの CivitAI pack を含めません

default LoRA pack のカテゴリ数:

- `base`: 1組
- `enhancement`: 2組
- `actions_vaginal`: 8組
- `actions_oral`: 4組
- `actions_manual`: 4組
- `actions_solo`: 2組
- `actions_specialty`: 1組
- `actions_motion`: 1組
- `effects_physics`: 3組
- `effects_fluid`: 6組
- `camera`: 1組
- `style`: 2組

運用メモ:

- `pov-missionary` は Lightx2v 併用時に HN 側 strength を `0` にする前提
- `masturbation-handjob` は trigger `handj0b` 前提
- `cinematic-closeup` は元ファイル名がスペース入りのため、queue file 側で `cinematic-closeup-high/low.safetensors` にリネーム
- cumshot / fluid 系は同時使用で競合しやすいので、シーンごとに 1 種ずつが前提

custom node の ref は、現時点の upstream HEAD commit に pin 済みです。`scripts/preset_audit.py` を回すと、`workflow_bundle / runpod_48gb / runpod_80gb` は警告なし、`research` だけが意図的な legacy/candidate 群を持つため警告ありになります。

workflow 依存の再抽出:

```bash
python3 scripts/workflow_dependency_report.py
```

preset 監査:

```bash
python3 scripts/preset_audit.py --md-out reports/preset_audit.md --json-out reports/preset_audit.json
```

## GitHub Actions で image build

ローカルで Docker を使わなくても、GitHub Actions で `linux/amd64` image を build して GHCR に push できます。workflow は [build-ghcr.yml](/home/kenic/repositories/wan_comfyui_template/.github/workflows/build-ghcr.yml:1) です。

- `pull_request`
  - build のみ
- `push` to `main`
  - build + GHCR push
- `push` tag `v*`
  - build + GHCR push
- `workflow_dispatch`
  - 手動実行。`push_image=false` なら build のみ

公開先 image 名:

- `ghcr.io/<github-owner>/<repo-name>:latest`
- `ghcr.io/<github-owner>/<repo-name>:sha-<commit>`
- tag push 時は `ghcr.io/<github-owner>/<repo-name>:vX.Y.Z`

最初に必要なこと:

1. この repo を GitHub に push
2. GitHub Actions を有効化
3. workflow を一度実行
4. GHCR package を public にする

RunPod で一番扱いやすいのは public GHCR image です。private image でも使えますが、RunPod template 側で registry credentials の設定が必要になります。

この image は `ComfyUI` 本体に加えて、template manifest に入っている custom node source と `SageAttention` source も image 内に同梱します。初回 Pod 起動時は image 内の `/opt/ComfyUI` と `/opt/template-node-cache` を `/workspace` 側へ展開するだけなので、RunPod 側で `github.com` へ到達できない環境でも起動できます。2回目以降は `/workspace` の Network Volume を再利用します。

`SageAttention` は `INSTALL_SAGEATTENTION=1` を明示したときだけ起動時に build します。build 前に `torch.cuda.is_available()` / `torch.cuda.get_device_capability()` を使った preflight を行い、RunPod ホスト driver と container 内の CUDA runtime が噛み合っていない場合は build を試さずに skip します。

運用上の注意:

- `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404` が持つ `torch` / CUDA stack をそのまま使う前提です
- host driver が古いノードでは `SageAttention` build は失敗するため、その場合は `--use-sage-attention` なしで起動させます
- `SageAttention` の失敗は optional 扱いで、ComfyUI 本体の起動失敗とは切り分けて見てください

CivitAI LoRA の追加取得:

```bash
# 直接 version_id / URL を渡す
CIVITAI_VERSIONS=2073605,2176505 python3 scripts/template_downloader.py --phase models

# queue file で渡す
CIVITAI_QUEUE_PATH=/workspace/civitai_queue.txt python3 scripts/template_downloader.py --phase models
```

queue file は [config/examples/civitai_queue.example.txt](/home/kenic/repositories/wan_comfyui_template/config/examples/civitai_queue.example.txt:1) を雛形にできます。`target_dir=loras/nsfw` のようなサブディレクトリ指定や `target_name` 上書きにも対応しています。

## 今後詰める項目

- CivitAI 側の high/low merged checkpoint 群の最新版選定
- `hf_models.json` の candidate 群を採用するかの判断
- DaSiWa / Kenpechi 系 workflow に含まれる NSFW LoRA 群を template 既定で持つかの判断
- RunPod 実機での cold start / warm start / workflow 読み込み smoke test
