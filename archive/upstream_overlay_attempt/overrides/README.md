`overrides/comfyui-wan/` に置いたファイルは、Docker build 時に upstream checkout `/comfyui-wan/` へそのまま上書きされます。

例:

- `overrides/comfyui-wan/src/start.sh`
- `overrides/comfyui-wan/workflows/Wan 2.1/Native-I2V-60FPS.json`
- `overrides/comfyui-wan/4xLSDIR.pth`

まずは 1 ファイルずつだけ差し替える運用にしてください。
