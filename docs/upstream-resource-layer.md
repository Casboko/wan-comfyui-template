# Upstream Resource Layer Strategy

## 目的

この repo の目的は、`Hearmeman24/comfyui-wan` の実行基盤を全面的に作り直すことではなく、upstream が取得している外部リソースだけを自分の用途に合わせて差し替えられるようにすることです。

対象になる外部リソース:

- custom nodes
- Hugging Face の weight / model / VAE / text encoder / detection model
- CivitAI の LoRA / model
- 配布 workflow

非目標:

- CUDA / PyTorch / ComfyUI 本体の独自運用
- upstream の起動骨格全体の置き換え
- node 依存の要求に合わせて GPU runtime を都度変えること

## 採用方針

採用する設計は、**upstream fixed + minimal overlay + manifest-driven resource layer** です。

要点:

1. upstream は fixed commit で取り込む
2. 起動経路は upstream にできるだけ寄せる
3. 差し替えるのは `Dockerfile` と `src/start.sh` の resource acquisition 部分に限定する
4. 「何を取るか」は manifest / preset で宣言する
5. node install で `torch` 系 runtime を壊さないよう制約を入れる

## この方針を採る理由

upstream では外部リソース取得が 2 箇所に分散しています。

- build 時の `Dockerfile`
  - custom node の clone / install
- 起動時の `src/start.sh`
  - node update
  - Hugging Face download
  - CivitAI download
  - workflow 配置

そのため、「取得対象だけを差し替える」には runtime 全体を書き換えるより、upstream の骨格を維持したまま取得部分だけ薄く置き換える方が保守しやすいです。

以前の manifest-first runtime は取得対象の自由度は高い一方で、upstream から離れすぎて CUDA / PyTorch の整合性まで自前で背負いました。実際に custom node の requirements から `torch` が CUDA 13 系へ上がり、ComfyUI 起動失敗を起こしました。現在はこの反省を踏まえ、overlay 方式を active 構成にしています。

## 責務の境界

### upstream から借りる責務

- base image と CUDA / PyTorch 前提
- ComfyUI install 手順
- workspace 初期化の骨格
- SageAttention 周辺の upstream 依存ロジック
- ComfyUI 起動引数の基準

### この repo で管理する責務

- custom node の採用一覧
- model / LoRA / workflow の採用一覧
- preset ごとの group 切り替え
- 取得対象の pin
- resource download / sync の実装
- dependency safety rule
- workflow から依存を棚卸しする補助スクリプト

## Active 構成

現在の active 構成は、`archive/upstream_overlay_attempt/` の発想を root へ引き上げたものです。

- [Dockerfile](/home/kenic/repositories/wan_comfyui_template/Dockerfile:1)
  - upstream `Hearmeman24/comfyui-wan` を fixed commit で checkout する
  - `config/`, `scripts/`, `template_workflows/`, `overrides/` を image に同梱する
  - upstream の hardcoded custom node bulk install は採らず、manifest から必要 node source だけを image 側に cache する
  - build 済み runtime から `torch` / `torchvision` / `torchaudio` / `triton` / `numpy` の constraints を生成する
- [overrides/comfyui-wan/src/start.sh](/home/kenic/repositories/wan_comfyui_template/overrides/comfyui-wan/src/start.sh:1)
  - upstream `src/start.sh` の代わりに動く overlay
  - preset を読み、workspace への seed と `template_downloader.py` 呼び出しを行う
  - bundled node cache も enabled node group に従って workspace へ seed する
  - workflow 配置も overlay 側から統一して行う
- [scripts/template_downloader.py](/home/kenic/repositories/wan_comfyui_template/scripts/template_downloader.py:1)
  - manifest / preset を読み、models と custom nodes を同期する
  - node install 時に constraints を適用する
  - locked runtime package を requirements から除外する
  - `install.py` 実行時にも `PYTHONPATH` と constraints を引き継ぐ

補助ファイル:

- [config/manifests/custom_nodes.json](/home/kenic/repositories/wan_comfyui_template/config/manifests/custom_nodes.json:1)
- [config/manifests/hf_models.json](/home/kenic/repositories/wan_comfyui_template/config/manifests/hf_models.json:1)
- [config/settings/](/home/kenic/repositories/wan_comfyui_template/config/settings)
- [template_workflows/](/home/kenic/repositories/wan_comfyui_template/template_workflows)
- [overrides/comfyui-wan/](/home/kenic/repositories/wan_comfyui_template/overrides/comfyui-wan)

## 実装ルール

### 1. runtime を壊す依存更新を禁止する

custom node の `requirements.txt` や `install.py` は、そのまま実行すると `torch` / `torchvision` / `torchaudio` / `triton` / `numpy` / `xformers` を上書きすることがあります。これは禁止です。

現在のルール:

- node install 時は `pip install -c <constraints> ...` を使う
- constraints には少なくとも以下を固定する
  - `torch`
  - `torchvision`
  - `torchaudio`
  - `triton`
  - `numpy`
- requirements 実行前に locked runtime package を走査する
- manifest 側 `runtime_lock_policy` で以下を選べる
  - `filter`
  - `error`
  - `allow`
- `install.py` 実行時も constraints と `PYTHONPATH` を継承する

補足:

- constraints file は現時点では image build 時に `/opt/template-pip/constraints-cu128.txt` として生成している
- repo 管理下の静的 constraints file はまだ追加していない

### 2. 取得対象は hardcode しない

node / model / LoRA / workflow の採否は、原則として manifest / preset から決まる状態にします。

例外は以下だけです。

- upstream bootstrap に必要な最小限の取得
- downloader 自身を動かすための最小依存

### 3. workflow 起点で manifest を作る

運用の起点は workflow です。

推奨フロー:

1. `template_workflows/` に workflow を置く
2. `scripts/workflow_dependency_report.py` で依存を抽出する
3. `config/manifests/*.json` に pin する
4. `config/settings/*.env` で preset を切る
5. `scripts/preset_audit.py` で監査する

### 4. upstream 差分は薄く保つ

overlay で持つ差分は「resource selection のために必要なもの」へ限定します。

基本方針:

- upstream に追従できる差分だけ持つ
- UI や起動骨格を大きく作り変えない
- upstream 側の改善を取り込みやすい状態を保つ

## 方式比較

### A. root の manifest-first runtime を継続する

利点:

- 自由度が高い
- 取得対象を完全に repo 側で制御できる

欠点:

- upstream から離れすぎる
- CUDA / PyTorch の整合性までこの repo が背負う
- 保守コストが高い

判断:

- 不採用

### B. `additional_params.sh` だけで upstream をねじる

利点:

- 差分は少ない

欠点:

- upstream の hardcoded resource acquisition を止めきれない
- source ではなく実行なので、環境注入ポイントとして弱い

判断:

- 不採用

### C. upstream fixed + minimal overlay + manifest-driven resource layer

利点:

- 目的に対して責務がちょうどよい
- upstream 追従性が高い
- resource selection を宣言的に管理できる
- runtime 破壊をガードしやすい

欠点:

- overlay 設計と constraints 設計が必要

判断:

- 採用

## 実装状況

### 反映済み

- root `Dockerfile` を upstream-overlay ベースに再構成
- `overrides/comfyui-wan/src/start.sh` を active overlay として追加
- `template_downloader.py` から models / nodes の同期を起動
- build 済み runtime から constraints file を生成
- node 側 `requirements.txt` の locked runtime package を filter する処理を追加

### 未完了

- 実イメージ build と RunPod 上の smoke test
- `minimal` preset と本命 preset の起動確認
- 必要に応じた manifest ごとの `runtime_lock_policy` の明示
- 必要なら repo 管理下の静的 constraints file への移行

## 検証方針

最初に確認する preset:

- `minimal`
  - 起動と torch stack 保全の確認
- 本命 preset
  - 必要 node と model だけで workflow が開くか

確認項目:

- ComfyUI が起動する
- `torch.cuda.is_available()` が壊れない
- `pip install` 後に `torch` version が変わらない
- workflow が要求する node pack が揃う
- `preset_audit.py` の警告が意図どおり

## 完了条件

以下を満たしたら、この repo は目的に対して正しい形になったとみなします。

- upstream の骨格で ComfyUI が起動する
- 取得対象の一覧が manifest / preset に集約されている
- hardcoded URL 群が overlay 内の限定箇所に閉じている
- node install で `torch` stack が変更されない
- `minimal` と本命 preset で smoke test が通る
- workflow 追加時に `workflow_dependency_report.py` から manifest 更新まで回せる

## 現時点の判断

この repo の正規方針は、runtime 全体を独自実装することではありません。

正規方針は:

- upstream の実行基盤を維持する
- resource acquisition を宣言的に置き換える
- その置換レイヤをこの repo で管理する

以後の設計判断は、この文書を基準に行います。
