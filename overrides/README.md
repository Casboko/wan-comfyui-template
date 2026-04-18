`overrides/comfyui-wan/` に置いたファイルは、Docker build 時に upstream checkout `/comfyui-wan/` へそのまま上書きされます。

この repo では、upstream の実行基盤を維持したまま resource acquisition 部分だけを差し替えるために使います。

主な差し替え対象:

- `overrides/comfyui-wan/src/start.sh`

workflow 本体は `template_workflows/` を正とし、overlay 側 `start.sh` から workspace へ配布します。
