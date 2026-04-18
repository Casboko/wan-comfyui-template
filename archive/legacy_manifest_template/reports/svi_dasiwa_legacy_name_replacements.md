# SVI pro / DaSiWa Legacy Name Replacement Candidates

Date checked: 2026-04-18 JST

Update after workflow rewrite:

- `SVI pro.json` no longer points at the old `comfyui_1030` FP8 checkpoint names.
- `SVI pro.json` no longer points at the wrong-family `t2v ... 1217` LoRA name.
- `DaSiWa` no longer exposes the old `wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors` metadata suggestion.
- The active LightX2V LoRA pair in `SVI pro.json` is now the `260412` high/low pair from `obsxrver/wan2.2-i2v-lightx2v-260412`.

Baseline policy for this template:

- Primary base weights: `wan2.2_i2v_high_noise_14B_fp16.safetensors`
- Primary base weights: `wan2.2_i2v_low_noise_14B_fp16.safetensors`
- Keep SVI LoRAs
- Exclude Lynx
- Main path uses `260412` Lightx2v LoRA on top of the official fp16 pair

## Keep As-Is

These names still fit the current direction and should not be treated as legacy just because they come from older repos:

- `SVI_v2_PRO_Wan2.2-I2V-A14B_HIGH_lora_rank_128_fp16.safetensors`
- `SVI_v2_PRO_Wan2.2-I2V-A14B_LOW_lora_rank_128_fp16.safetensors`
- `wan_2.1_vae.safetensors`
- `umt5_xxl_fp8_e4m3fn_scaled.safetensors`

## SVI pro.json

### 1. FP8 ComfyUI checkpoints

Current strings:

- `wan2.2\wan2.2_i2v_A14b_high_noise_scaled_fp8_e4m3_lightx2v_4step_comfyui_1030.safetensors`
  - line: 3968
- `wan2.2\wan2.2_i2v_A14b_low_noise_scaled_fp8_e4m3_lightx2v_4step_comfyui.safetensors`
  - line: 4019

Current role:

- Active `UNETLoader` widget values

Why they are legacy in this template:

- They point to pre-`260412` FP8/ComfyUI variants.
- The current template baseline is the newer `720p_260412` BF16 pair.

Preferred action:

- Replace both with the `260412` BF16 pair.

Preferred replacement:

- `wan2.2_i2v_A14b_high_noise_lightx2v_4step_720p_260412.safetensors`
- `wan2.2_i2v_A14b_low_noise_lightx2v_4step_720p_260412.safetensors`

Alternate replacement only if we intentionally keep an FP8 preset path:

- `wan2.2_i2v_A14b_high_noise_scaled_fp8_e4m3_lightx2v_4step.safetensors`
- `wan2.2_i2v_A14b_low_noise_scaled_fp8_e4m3_lightx2v_4step.safetensors`

Risk note:

- LightX2V publishes both generic FP8 files and older `comfyui`-named FP8 files. For ComfyUI-native loading, the plain FP8 names need practical verification before becoming the default.

Confidence:

- High for BF16 `260412` as preferred replacement
- Medium for the generic FP8 pair as a direct ComfyUI replacement

### 2. Wrong-family T2V LoRA in I2V workflow

Current string:

- `lightx2v\wan2.2_t2v_A14b_high_noise_lora_rank64_lightx2v_4step_1217.safetensors`
  - line: 1205

Current role:

- Active `LoraLoaderModelOnly` widget value

Why it is legacy/problematic:

- It is a `t2v` LoRA name inside an I2V workflow.
- The current official I2V LoRA pair in LightX2V is the `1022` pair, not `1217`.

Preferred action:

- Remove this node from the active path if the workflow is standardized on merged `260412` base checkpoints.

Compat-only replacement if the workflow keeps external Lightx2v LoRAs:

- `wan2.2_i2v_A14b_high_noise_lora_rank64_lightx2v_4step_1022.safetensors`

Confidence:

- High

### 3. I2V low-noise 1022 LoRA

Current string:

- `lightx2v\wan2.2_i2v_A14b_low_noise_lora_rank64_lightx2v_4step_1022.safetensors`
  - line: 1262

Current role:

- Active `LoraLoaderModelOnly` widget value

Why it is legacy in this template:

- It belongs to the separate-LoRA path, while the template baseline is moving to merged `260412` base checkpoints.

Preferred action:

- Remove from the active path if `SVI pro.json` is converted to direct `260412` loading.

Compat-only keep option:

- Keep only in the compat preset alongside the matching high-noise I2V `1022` LoRA.

Confidence:

- High

### 4. Wan2.1-era fallback Lightx2v LoRA metadata

Current string:

- `lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors`
  - lines: 966, 1190, 1247, 1304

Current role:

- Candidate metadata in `properties.models`
- Not the current `widgets_values`

Why it is legacy:

- It is the older Wan2.1/480p fallback family.
- It is no longer aligned with the `260412` Wan2.2 merged-base direction.

Preferred action:

- Remove from node metadata once the workflow is fully migrated.

Compat-only keep option:

- Keep only in research/compat presets if we still want to test old Kijai fallback behavior.

Confidence:

- High

### 5. Kijai Animate checkpoint metadata

Current string:

- `Wan2_2-Animate-14B_fp8_e4m3fn_scaled_KJ.safetensors`
  - lines: 3954, 4005

Current role:

- Candidate metadata in `UNETLoader.properties.models`
- Not the currently selected checkpoint value

Why it is legacy for this template:

- It represents a different model family than the chosen `260412` I2V Lightx2v baseline.

Preferred action:

- Replace the metadata entry with the actual baseline filenames used by the workflow, or remove the stale metadata entirely.

Suggested replacement metadata:

- `wan2.2_i2v_A14b_high_noise_lightx2v_4step_720p_260412.safetensors`
- `wan2.2_i2v_A14b_low_noise_lightx2v_4step_720p_260412.safetensors`

Confidence:

- High

### 6. Documentation-only legacy URL block

Current references:

- `wan2.2_i2v_A14b_high_noise_scaled_fp8_e4m3_lightx2v_4step_comfyui.safetensors`
- `https://huggingface.co/Kijai/WanVideo_comfy/tree/main/LoRAs/Stable-Video-Infinity/v2.0`
  - line: 3169

Current role:

- Note / documentation text only

Preferred action:

- Update the note to mention the `260412` pair and the actual template preset policy.

Confidence:

- High

## DaSiWa WAN 2.2 i2v FastFidelity C-SVI-34.json

### 1. Old low-noise-only Lightx2v v1 LoRA metadata

Current string:

- `wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors`
  - line: 12571

Current role:

- Candidate metadata in `properties.models`
- Not the active selected `widgets_values`

Why it is legacy:

- It is the older v1 low-noise-only LoRA naming.
- The current official Wan2.2 I2V distill LoRA naming is the `1022` high/low pair.
- The template baseline is moving to merged `260412` base checkpoints, so a separate low-noise-only v1 candidate is no longer a good default suggestion.

Preferred action:

- Remove the stale metadata entry.

Compat-only replacement if we still want a separate-LoRA path:

- `wan2.2_i2v_A14b_low_noise_lora_rank64_lightx2v_4step_1022.safetensors`

Confidence:

- High

### 2. Kijai SVI LoRA references

Current strings:

- `WAN22/F/SVI_v2_PRO_Wan2.2-I2V-A14B_HIGH_lora_rank_128_fp16.safetensors`
  - line: 12583
- `WAN22/F/SVI_v2_PRO_Wan2.2-I2V-A14B_LOW_lora_rank_128_fp16.safetensors`
  - line: 12636

Current role:

- Active `widgets_values`

Action:

- Keep as-is

Why:

- These are still aligned with the intended SVI path and are not the legacy naming we are trying to eliminate.

Confidence:

- High

### 3. Documentation-only Kijai URLs

Current references:

- Kijai SVI LoRA URLs in the markdown note
  - line: 5041

Current role:

- Documentation text only

Action:

- Optional cleanup only

Why:

- They are not blocking migration to the `260412` base.

Confidence:

- High

## Recommended migration order

1. `SVI pro.json`
   - Replace the two active FP8 checkpoint names with the `260412` pair.
   - Remove the `t2v` LoRA reference.
   - Decide whether to remove the remaining I2V `1022` LoRA path entirely or keep it in compat mode.
   - Clean up stale `properties.models` metadata.
2. `DaSiWa`
   - Remove the old v1 low-noise metadata entry.
   - Leave SVI LoRAs untouched.
3. Notes / embedded documentation
   - Update explanatory text to match the new baseline and preset policy.
