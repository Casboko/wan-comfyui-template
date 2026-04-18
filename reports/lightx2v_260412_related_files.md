# Lightx2v 260412 Related Files

Date checked: 2026-04-18 JST

## Confirmed baseline

As of 2026-04-18, the template baseline is:

- official base model pair:
  - `wan2.2_i2v_high_noise_14B_fp16.safetensors`
  - `wan2.2_i2v_low_noise_14B_fp16.safetensors`
- plus `obsxrver/wan2.2-i2v-lightx2v-260412` LoRA pair:
  - `wan2.2_i2v_A14b_high_noise_lora_rank64_lightx2v_4step_720p_260412.safetensors`
  - `wan2.2_i2v_A14b_low_noise_lora_rank64_lightx2v_4step_720p_260412.safetensors`

Primary sources:

- https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/tree/main/split_files/diffusion_models
- https://huggingface.co/obsxrver/wan2.2-i2v-lightx2v-260412/tree/main

Notes:

- Both high-noise and low-noise files are still required.
- The same `obsxrver` repo also exposes the lightweight FP8 merged pair used by the 48GB preset:
  - `wan2.2_i2v_A14b_high_noise_scaled_fp8_e4m3_lightx2v_4step_comfyui_720p_260412.safetensors`
  - `wan2.2_i2v_A14b_low_noise_scaled_fp8_e4m3_lightx2v_4step_comfyui_720p_260412.safetensors`

## 48GB / 80GB implication

LightX2V's Wan2.2 beginner guide reports the following single-H100 I2V peaks:

- Base Wan2.2-I2V-A14B: about 79.1 GiB without offload
- Base Wan2.2-I2V-A14B: about 43.7 GiB with `cpu_offload=true`
- Distill merged model: about 79.1 GiB without offload
- Distill merged model: about 34.4 GiB with `cpu_offload=true`
- Distill FP8 model: about 47.3 GiB without offload
- Distill FP8 model: about 29.3 GiB with `cpu_offload=true`

Primary source:

- `/tmp/LightX2V-upstream/examples/BeginnerGuide/ZH_CN/Wan22-moe.md`

Practical interpretation:

- 80GB class: official fp16 pair + `260412` LoRA pair is now the default target.
- 48GB class: use the `obsxrver` FP8 merged pair via the dedicated FP8 preset/workflows.

## Current template workflow dependencies

Files directly referenced by the workflows that remain in the active template presets:

- BF16 text encoder: `umt5-xxl-enc-bf16.safetensors`
- FP8 text encoder: `umt5_xxl_fp8_e4m3fn_scaled.safetensors`
- VAE: `wan_2.1_vae.safetensors`
- CLIP visual/text sidecar: `open-clip-xlm-roberta-large-vit-huge-14_visual_fp16.safetensors`
- CLIP vision sidecar: `clip_vision_h.safetensors`
- SVI LoRAs:
  - `SVI_v2_PRO_Wan2.2-I2V-A14B_HIGH_lora_rank_128_fp16.safetensors`
  - `SVI_v2_PRO_Wan2.2-I2V-A14B_LOW_lora_rank_128_fp16.safetensors`

Local references:

- `template_workflows/SVI pro.json`
- `template_workflows/Wan2.2_I2V_SVI_Kenpechi_Workflow_v3.5 12Sec (3).json`
- `template_workflows/DaSiWa WAN 2.2 i2v FastFidelity C-SVI-34.json`

Excluded from the active presets:

- `template_workflows/WAN 2.2 I2V.json`
- Lynx sidecars such as `lynx_lite_resampler_fp32.safetensors` and `Wan2_1-T2V-14B-Lynx_lite_ip_layers_fp16.safetensors`

## Compatibility-only files still worth keeping

These are still useful while the bundled workflows are being migrated away from older Kijai naming:

- Legacy workflow extras:
  - `lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors`
  - `Wan_2_2_I2V_A14B_HIGH_lightx2v_MoE_distill_lora_rank_64_bf16.safetensors`
  - `Wan21_I2V_14B_lightx2v_cfg_step_distill_lora_rank64.safetensors`

Primary sources:

- https://huggingface.co/obsxrver/wan2.2-i2v-lightx2v-260412/tree/main
- local workflow JSON references listed above

Template manifest policy after the latest cleanup:

- `lightx2v_compat`
  - the `obsxrver` `260412` high/low I2V LoRA pair used by the main workflows
- `lightx2v_legacy`
  - Kijai / Wan2.1 fallback extras kept only for research or rollback

## Native LightX2V vs ComfyUI difference

LightX2V native loading expects more than the DIT pair:

- model `config.json`
- T5 encoder
- VAE
- tokenizer directories
- sometimes CLIP-related sidecars depending on the path you use

Primary sources:

- https://lightx2v-en.readthedocs.io/en/latest/getting_started/model_structure.html
- https://huggingface.co/lightx2v/Encoders/tree/main

For the current template direction, the immediate priority remains the ComfyUI-format sidecars listed above. Lynx is intentionally excluded from the active template presets, while the official fp16 pair is now back in the main path.
