# --- Wan2.2 I2V A14B + SVI 2.0 Pro + Remix NSFW + CivitAI LoRA Downloader v6.0 (robust) ---
# 更新点（2026-04-16）:
#   v6.0:
#   - CivitAI ダウンローダを robust 実装に置き換え（旧 civitai_robust.py を統合）
#       - civitai.com / civitai.red の両ドメイン自動 fallback
#       - DL URL を複数パターン生成して順次試行
#         (API downloadUrl → ドメイン差し替え → /api/download/models/{id} → fileId 指定)
#       - aria2c 失敗時に requests へ自動 fallback
#       - 401 / 403 / 404 に対する明示的な原因分析（Early Access、地域制限、移行済み等）
#       - S3 リダイレクト時の Authorization 消失対策（query token を保険として付与）
#   - CIVITAI_DOMAIN_PREFER env 追加（"com" or "red"。NSFW寄りなら "red" 先がおすすめ）
#   - manifest に attempts フィールドを追加（DL 試行履歴、デバッグ用）
#
#   v5.0 までの更新点はそのまま継承:
#   - SVI 2.0 Pro LoRA (HIGH/LOW)、Wan22-Lightning、Wan22 I2V Lightx2v、
#     Wan2.2 Remix NSFW (opt-in)、rCM (opt-in)、NSFW Wan UMT5-XXL (opt-in)、
#     必須カスタムノード一式（KJNodes / VHS / GGUF / VFI / rgthree / Manager）
#

# === KEY=VALUE テキスト設定ファイルを読み込む（.env不要） ===
import os, sys
from pathlib import Path

def _parse_settings_file(path: Path):
    out = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for i, raw in enumerate(f, 1):
                line = raw.strip()
                if not line or line.startswith(("#", ";")):
                    continue
                if "=" not in line:
                    print(f"[WARN] settings line {i} ignored (no '='): {raw.rstrip()}")
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                    v = v[1:-1]
                v = os.path.expandvars(os.path.expanduser(v))
                out[k] = v
    except FileNotFoundError:
        return {}
    return out

def _settings_path_from_argv(argv):
    for i, a in enumerate(argv[1:], 1):
        if a.startswith("--settings="):
            return Path(a.split("=", 1)[1]).expanduser().resolve()
        if a == "--settings" and i + 1 < len(argv):
            return Path(argv[i + 1]).expanduser().resolve()
    return None

def _default_settings_path():
    try:
        return (Path(__file__).resolve().parent / "downloader_settings.txt")
    except NameError:
        return Path("downloader_settings.txt").resolve()

_SETTINGS_FILE = _settings_path_from_argv(sys.argv) or Path(os.environ.get("DOWNLOADER_SETTINGS_PATH", str(_default_settings_path()))).expanduser()
_loaded = _parse_settings_file(_SETTINGS_FILE)
if _loaded:
    os.environ.update(_loaded)
    print(f"[INFO] Loaded {len(_loaded)} keys from settings: {_SETTINGS_FILE}")
else:
    print(f"[INFO] Settings file not found or empty: {_SETTINGS_FILE} (env/defaults will be used)")
# === [END] ===

# 使い方（最小）:
#   $ python downloader_plus_civitai_v6_robust.py
#   → Wan2.2 base + Lightx2v I2V LoRA + SVI 2.0 Pro LoRA を DL
# CivitAI も合わせて DL する場合:
#   $ CIVITAI_TOKEN=xxx CIVITAI_VERSIONS=2073605,2176505 python downloader_plus_civitai_v6_robust.py
# NSFW モデルで civitai.red を優先したい場合:
#   $ CIVITAI_DOMAIN_PREFER=red CIVITAI_TOKEN=xxx CIVITAI_VERSIONS=... python ...

import os, json, time, shutil, re, subprocess, sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Tuple

# ===== HF 系オプション =====
INCLUDE_LIGHTX2V = os.environ.get("INCLUDE_LIGHTX2V", "True").lower() in ("1","true","yes")
USE_HF_TRANSFER  = os.environ.get("USE_HF_TRANSFER",  "False").lower() in ("1","true","yes")
FORCE_REDOWNLOAD = os.environ.get("FORCE_REDOWNLOAD", "False").lower() in ("1","true","yes")
# 重要: 空文字列を None に変換。
#       HF_TOKEN="" のまま hf_hub_download に渡すと "Authorization: Bearer "
#       (空 token) が送られて全 DL が失敗する。
_hf_token_raw = os.environ.get("HF_TOKEN", "").strip()
HF_TOKEN = _hf_token_raw if _hf_token_raw else None

# ===== Lightx2v ソース =====
LIGHTX2V_SOURCE  = os.environ.get("LIGHTX2V_SOURCE", "kijai").strip().lower()
LIGHTX2V_VARIANT = os.environ.get("LIGHTX2V_VARIANT", "I2V").strip().upper()
LIGHTX2V_RANKS   = [r.strip() for r in os.environ.get("LIGHTX2V_RANKS", "32,64,128").split(",") if r.strip()]

# ===== Wan22-Lightning =====
WAN22_LIGHTNING_SOURCE = os.environ.get("WAN22_LIGHTNING_SOURCE", "kijai").strip().lower()
INCLUDE_WAN22_LIGHTNING = os.environ.get("INCLUDE_WAN22_LIGHTNING", "True").lower() in ("1","true","yes","on")

# ===== Wan22 I2V Lightx2v LoRA =====
INCLUDE_WAN22_I2V_LIGHTX2V = os.environ.get("INCLUDE_WAN22_I2V_LIGHTX2V", "True").lower() in ("1","true","yes","on")

# ===== Wan21 I2V 低ノイズ fallback LoRA =====
INCLUDE_WAN21_I2V_LOW_LORA = os.environ.get("INCLUDE_WAN21_I2V_LOW_LORA", "1").lower() in ("1","true","yes","on")

# ===== Lynx =====
INCLUDE_LYNX     = os.environ.get("INCLUDE_LYNX", "0").lower() in ("1","true","yes","on")
LYNX_FLAVOR      = os.environ.get("LYNX_FLAVOR", "lite").strip().lower()
LYNX_INCLUDE_REF = os.environ.get("LYNX_INCLUDE_REF", "0").lower() in ("1","true","yes","on")

# ===== SVI 2.0 Pro =====
INCLUDE_SVI_PRO = os.environ.get("INCLUDE_SVI_PRO", "1").lower() in ("1","true","yes","on")
SVI_PRO_VARIANTS = [v.strip().upper() for v in os.environ.get("SVI_PRO_VARIANTS", "HIGH,LOW").split(",") if v.strip()]

# ===== Wan2.2 Remix NSFW =====
INCLUDE_WAN22_REMIX = os.environ.get("INCLUDE_WAN22_REMIX", "0").lower() in ("1","true","yes","on")
WAN22_REMIX_VERSION = os.environ.get("WAN22_REMIX_VERSION", "v2.0").strip()

# ===== rCM (TurboDiffusion) =====
INCLUDE_RCM = os.environ.get("INCLUDE_RCM", "0").lower() in ("1","true","yes","on")

# ===== NSFW Wan UMT5-XXL =====
INCLUDE_NSFW_T5 = os.environ.get("INCLUDE_NSFW_T5", "0").lower() in ("1","true","yes","on")

# ===== パフォーマンス pip =====
INSTALL_PERF_DEPS = os.environ.get("INSTALL_PERF_DEPS", "0").lower() in ("1","true","yes","on")
PERF_DEPS = [p.strip() for p in os.environ.get("PERF_DEPS", "sageattention,triton").split(",") if p.strip()]

# ===== CivitAI オプション（v6 で robust 化） =====
# 注意 (2026-04): CivitAI は civitai.com / civitai.red の2ドメイン体制に分割済み。
# モデルによってはどちらか片方にしか存在しない / 移行済みのケースがあるため、両方試す。
# CIVITAI_DOMAIN_PREFER=red にすると civitai.red を先に試す（NSFW モデル向け）
CIVITAI_TOKEN = os.environ.get("CIVITAI_TOKEN", "").strip()
USE_ARIA2C = os.environ.get("USE_ARIA2C", "0") in ("1","true","yes","on")
CIVITAI_FORCE_REDOWNLOAD = os.environ.get("CIVITAI_FORCE_REDOWNLOAD", "0") in ("1","true","yes","on")
CIVITAI_ONLY_SAFETENSORS = os.environ.get("CIVITAI_ONLY_SAFETENSORS", "1") in ("1","true","yes","on")
_DOMAIN_PREFER = os.environ.get("CIVITAI_DOMAIN_PREFER", "com").strip().lower()
if _DOMAIN_PREFER == "red":
    CIVITAI_DOMAINS = ["civitai.red", "civitai.com"]
else:
    CIVITAI_DOMAINS = ["civitai.com", "civitai.red"]

CIVITAI_REQUEST_TIMEOUT = int(os.environ.get("CIVITAI_REQUEST_TIMEOUT", "60"))
CIVITAI_DL_TIMEOUT = int(os.environ.get("CIVITAI_DL_TIMEOUT", "600"))

def _ensure(pkgs):
    import importlib, subprocess, sys
    miss=[p for p in pkgs if not importlib.util.find_spec(p.split("[")[0])]
    if miss:
        cmd=[sys.executable,"-m","pip","install","-U"]+miss
        if USE_HF_TRANSFER and "huggingface_hub" in pkgs:
            cmd[-1] = "huggingface_hub[hf_transfer]"
        subprocess.check_call(cmd)
_ensure(["huggingface_hub","requests"])
import requests
from huggingface_hub import hf_hub_download

# ===== 任意 perf 依存 pip install =====
if INSTALL_PERF_DEPS and PERF_DEPS:
    print(f"[INFO] Installing perf deps: {', '.join(PERF_DEPS)}")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-U"] + PERF_DEPS, timeout=900)
        print("[INFO] Perf deps installed.")
    except Exception as e:
        print(f"[WARN] Perf deps install failed: {e}")
        print("[WARN] sageattention/triton/flash-attn は環境依存。CUDA/PyTorch バージョン要確認。")

if USE_HF_TRANSFER:
    os.environ["HF_HUB_ENABLE_HF_TRANSFER"]="1"

# ===== ComfyUI ディレクトリ =====
COMFY_BASE = os.environ.get("COMFYUI_BASE", "/ComfyUI").strip()
COMFY = Path(COMFY_BASE).expanduser().resolve()
DM = (COMFY / "models" / "diffusion_models")
TE = (COMFY / "models" / "text_encoders")
LOR = (COMFY / "models" / "loras")
VAE = (COMFY / "models" / "vae")
CV = (COMFY / "models" / "clip_vision")
for p in (DM, TE, LOR, VAE, CV):
    p.mkdir(parents=True, exist_ok=True)

# ===== 共通 utility（早めに定義） =====
def _which(cmd: str) -> bool:
    return shutil.which(cmd) is not None

def validate_safetensors_header(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(8)
            if len(head) < 8:
                return False
            import struct
            (n,) = struct.unpack("<Q", head)
            if n <= 0 or n > 100*1024*1024:
                return False
            f.seek(8 + n)
            return True
    except Exception:
        return False

def bytes_to_gib(b): return b/(1024**3)
def dec_gb_to_gib(g): return (g*1000**3)/(1024**3) if g else 0.0

# ===== Wan 2.2 既存 DL =====
items = [
    dict(repo="Comfy-Org/Wan_2.2_ComfyUI_Repackaged",
         filename="split_files/diffusion_models/wan2.2_i2v_high_noise_14B_fp16.safetensors",
         dst=DM/"wan2.2_i2v_high_noise_14B_fp16.safetensors", size_gb_dec=28.6),
    dict(repo="Comfy-Org/Wan_2.2_ComfyUI_Repackaged",
         filename="split_files/diffusion_models/wan2.2_i2v_low_noise_14B_fp16.safetensors",
         dst=DM/"wan2.2_i2v_low_noise_14B_fp16.safetensors", size_gb_dec=28.6),
    dict(repo="Comfy-Org/Wan_2.1_ComfyUI_repackaged",
         filename="split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors",
         dst=TE/"umt5_xxl_fp8_e4m3fn_scaled.safetensors", size_gb_dec=6.74),
    dict(repo="ricecake/wan21NSFWClipVisionH_v10",
         filename="wan21NSFWClipVisionH_v10.safetensors",
         dst=CV/"nsfw_clip_vision_h.safetensors", size_gb_dec=3.94),
    dict(repo="Comfy-Org/Wan_2.1_ComfyUI_repackaged",
         filename="split_files/vae/wan_2.1_vae.safetensors",
         dst=VAE/"wan_2.1_vae.safetensors", size_gb_dec=0.254),
]

# ===== Lightx2v LoRA =====
SIZES_I2V = {"4":0.0544,"8":0.100,"16":0.191,"32":0.373,"64":0.738,"128":1.47,"256":2.92}
SIZES_T2V = {"4":0.0465,"8":0.0854,"16":0.163,"32":0.319,"64":0.631,"128":1.25,"256":2.50}

if INCLUDE_LIGHTX2V:
    if LIGHTX2V_SOURCE == "kijai":
        repo = "Kijai/WanVideo_comfy"
        for r in LIGHTX2V_RANKS:
            if LIGHTX2V_VARIANT == "I2V":
                fname = f"Lightx2v/lightx2v_I2V_14B_480p_cfg_step_distill_rank{r}_bf16.safetensors"
                size = SIZES_I2V.get(r, 0.0)
            elif LIGHTX2V_VARIANT == "T2V":
                fname = f"Lightx2v/lightx2v_T2V_14B_cfg_step_distill_v2_lora_rank{r}_bf16.safetensors"
                size = SIZES_T2V.get(r, 0.0)
            else:
                raise ValueError(f"Unsupported LIGHTX2V_VARIANT: {LIGHTX2V_VARIANT}")
            items.append(dict(repo=repo, filename=fname, dst=(LOR/Path(fname).name), size_gb_dec=size))
        print(f"[INFO] Lightx2v (Kijai) queued: variant={LIGHTX2V_VARIANT} ranks={LIGHTX2V_RANKS}")
    elif LIGHTX2V_SOURCE == "official":
        items += [
            dict(repo="lightx2v/Wan2.2-Lightning",
                 filename="Wan2.2-I2V-A14B-4steps-lora-rank64-Seko-V1/high_noise_model.safetensors",
                 dst=LOR/"Wan2.2-I2V-A14B-4steps-lora-rank64-Seko-V1_high_noise.safetensors", size_gb_dec=1.23),
            dict(repo="lightx2v/Wan2.2-Lightning",
                 filename="Wan2.2-I2V-A14B-4steps-lora-rank64-Seko-V1/low_noise_model.safetensors",
                 dst=LOR/"Wan2.2-I2V-A14B-4steps-lora-rank64-Seko-V1_low_noise.safetensors", size_gb_dec=1.23),
        ]
        print("[INFO] Lightx2v (official) queued: Seko-V1 high/low")
    else:
        raise ValueError(f"Unsupported LIGHTX2V_SOURCE: {LIGHTX2V_SOURCE}")

# ===== Wan22-Lightning =====
if INCLUDE_WAN22_LIGHTNING:
    if WAN22_LIGHTNING_SOURCE in ("kijai", "both"):
        items += [
            dict(repo="Kijai/WanVideo_comfy",
                 filename="LoRAs/Wan22-Lightning/Wan22_A14B_T2V_HIGH_Lightning_4steps_lora_250928_rank128_fp16.safetensors",
                 dst=LOR/"Wan22_A14B_T2V_HIGH_Lightning_4steps_lora_250928_rank128_fp16.safetensors",
                 size_gb_dec=1.23),
            dict(repo="Kijai/WanVideo_comfy",
                 filename="LoRAs/Wan22-Lightning/Wan22_A14B_T2V_LOW_Lightning_4steps_lora_250928_rank64_fp16.safetensors",
                 dst=LOR/"Wan22_A14B_T2V_LOW_Lightning_4steps_lora_250928_rank64_fp16.safetensors",
                 size_gb_dec=0.614),
        ]
        print("[INFO] Wan22-Lightning 250928 (Kijai mirror) queued: HIGH/LOW")
    if WAN22_LIGHTNING_SOURCE in ("official", "both"):
        items += [
            dict(repo="lightx2v/Wan2.2-Lightning",
                 filename="Wan2.2-T2V-A14B-4steps-lora-250928/high_noise_model.safetensors",
                 dst=LOR/"Wan2.2-T2V-A14B-4steps-lora-250928_high_noise.safetensors",
                 size_gb_dec=1.23),
            dict(repo="lightx2v/Wan2.2-Lightning",
                 filename="Wan2.2-T2V-A14B-4steps-lora-250928/low_noise_model.safetensors",
                 dst=LOR/"Wan2.2-T2V-A14B-4steps-lora-250928_low_noise.safetensors",
                 size_gb_dec=1.23),
        ]
        print("[INFO] Wan22-Lightning 250928 (official) queued: high/low_noise")

# ===== Wan22_Lightx2v I2V =====
if INCLUDE_WAN22_I2V_LIGHTX2V:
    items += [
        dict(repo="Kijai/WanVideo_comfy",
             filename="LoRAs/Wan22_Lightx2v/Wan_2_2_I2V_A14B_HIGH_lightx2v_MoE_distill_lora_rank_64_bf16.safetensors",
             dst=LOR/"Wan_2_2_I2V_A14B_HIGH_lightx2v_MoE_distill_lora_rank_64_bf16.safetensors",
             size_gb_dec=0.631),
        dict(repo="lightx2v/Wan2.2-I2V-A14B-Moe-Distill-Lightx2v",
             filename="loras/low_noise_model_rank64.safetensors",
             dst=LOR/"Wan2.2-I2V-A14B-Moe-Distill-Lightx2v_low_noise_model_rank64.safetensors",
             size_gb_dec=0.742),
    ]
    print("[INFO] Wan22_Lightx2v I2V queued: Kijai HIGH (rank64 bf16) + official LOW (rank64)")

# ===== Wan2.1 I2V fallback =====
if INCLUDE_WAN21_I2V_LOW_LORA:
    items += [
        dict(repo="lightx2v/Wan2.1-I2V-14B-480P-StepDistill-CfgDistill-Lightx2v",
             filename="loras/Wan21_I2V_14B_lightx2v_cfg_step_distill_lora_rank64.safetensors",
             dst=LOR/"Wan21_I2V_14B_lightx2v_cfg_step_distill_lora_rank64.safetensors",
             size_gb_dec=0.739),
    ]
    print("[INFO] Fallback (Wan2.1 I2V low-noise LoRA rank64) queued.")

# ===== Lynx =====
if INCLUDE_LYNX:
    lynx_repo = "Kijai/WanVideo_comfy"
    if LYNX_FLAVOR == "full":
        res_file = "Lynx/lynx_full_resampler_fp32.safetensors"
        ip_file  = "Lynx/Wan2_1-T2V-14B-Lynx_full_ip_layers_fp16.safetensors"
        ip_sz    = 4.2
    else:
        res_file = "Lynx/lynx_lite_resampler_fp32.safetensors"
        ip_file  = "Lynx/Wan2_1-T2V-14B-Lynx_lite_ip_layers_fp16.safetensors"
        ip_sz    = 0.839
    items += [
        dict(repo=lynx_repo, filename=res_file, dst=DM/Path(res_file).name, size_gb_dec=0.344 if "full" in res_file else 0.328),
        dict(repo=lynx_repo, filename=ip_file,  dst=DM/Path(ip_file).name,  size_gb_dec=ip_sz),
    ]
    if LYNX_INCLUDE_REF:
        ref_file = "Lynx/Wan2_1-T2V-14B-Lynx_full_ref_layers_fp16.safetensors"
        items.append(dict(repo=lynx_repo, filename=ref_file, dst=DM/Path(ref_file).name, size_gb_dec=4.2))
    print(f"[INFO] Lynx queued: flavor={LYNX_FLAVOR} include_ref={LYNX_INCLUDE_REF}")

# ===== SVI 2.0 Pro LoRA =====
if INCLUDE_SVI_PRO:
    svi_repo = "Kijai/WanVideo_comfy"
    svi_dir = "LoRAs/Stable-Video-Infinity/v2.0"
    svi_files = {
        "HIGH": ("SVI_v2_PRO_Wan2.2-I2V-A14B_HIGH_lora_rank_128_fp16.safetensors", 1.47),
        "LOW":  ("SVI_v2_PRO_Wan2.2-I2V-A14B_LOW_lora_rank_128_fp16.safetensors",  1.47),
    }
    queued = []
    for variant in SVI_PRO_VARIANTS:
        if variant not in svi_files:
            print(f"[WARN] Unknown SVI_PRO_VARIANTS entry: {variant} (expected HIGH or LOW)")
            continue
        fname, sz = svi_files[variant]
        items.append(dict(repo=svi_repo, filename=f"{svi_dir}/{fname}", dst=LOR/fname, size_gb_dec=sz))
        queued.append(variant)
    if queued:
        print(f"[INFO] SVI 2.0 Pro queued: {', '.join(queued)} (rank 128 fp16)")
    else:
        print("[WARN] SVI_PRO_VARIANTS empty after filtering; nothing queued.")

# ===== Wan2.2 Remix NSFW =====
if INCLUDE_WAN22_REMIX:
    remix_repo = "FX-FeiHou/wan2.2-Remix"
    if WAN22_REMIX_VERSION == "v2.0":
        items += [
            dict(repo=remix_repo,
                 filename="NSFW/Wan2.2_Remix_NSFW_i2v_14b_high_lighting_v2.0.safetensors",
                 dst=DM/"Wan2.2_Remix_NSFW_i2v_14b_high_lighting_v2.0.safetensors",
                 size_gb_dec=14.3),
            dict(repo=remix_repo,
                 filename="NSFW/Wan2.2_Remix_NSFW_i2v_14b_low_lighting_v2.0.safetensors",
                 dst=DM/"Wan2.2_Remix_NSFW_i2v_14b_low_lighting_v2.0.safetensors",
                 size_gb_dec=14.3),
        ]
        print(f"[INFO] Wan2.2 Remix NSFW queued: I2V {WAN22_REMIX_VERSION} (HIGH+LOW)")
    else:
        print(f"[WARN] WAN22_REMIX_VERSION={WAN22_REMIX_VERSION} は未対応。v2.0 のみ実装。")
        print(f"[WARN] v2.1/v3.0 を使う場合は CivitAI 経由（CIVITAI_VERSIONS に modelVersionId 追加）")

# ===== rCM =====
if INCLUDE_RCM:
    items += [
        dict(repo="thu-ml/TurboWan2.2-I2V-A14B-720P",
             filename="model.safetensors",
             dst=DM/"TurboWan2.2-I2V-A14B-720P.safetensors",
             size_gb_dec=28.0),
    ]
    print("[INFO] rCM (TurboDiffusion Wan2.2 I2V 720P) queued.")
    print("[WARN] rCM はリサーチ実装。ファイル名や repo 構造が変わる可能性あり、要確認。")
    print("       https://github.com/thu-ml/TurboDiffusion")

# ===== NSFW Wan UMT5-XXL =====
if INCLUDE_NSFW_T5:
    items += [
        dict(repo="NSFW-API/NSFW-Wan-UMT5-XXL",
             filename="nsfw_wan_umt5-xxl_fp8_scaled.safetensors",
             dst=TE/"nsfw_wan_umt5-xxl_fp8_scaled.safetensors",
             size_gb_dec=6.74),
    ]
    print("[INFO] NSFW Wan UMT5-XXL (fp8_scaled) queued.")
    print("       Wan2.2 Remix や NSFW ワークフローでの標準テキストエンコーダ")

# ===== カスタムノードカタログ =====
INSTALL_NODES = os.environ.get("INSTALL_NODES", "0").lower() in ("1", "true", "yes", "on")

NODES_WANWRAPPER_REPO = os.environ.get("NODES_WANWRAPPER_REPO", "https://github.com/kijai/ComfyUI-WanVideoWrapper.git").strip()
NODES_WANWRAPPER_REF = os.environ.get("NODES_WANWRAPPER_REF", "main").strip()
NODES_KJNODES_REPO = os.environ.get("NODES_KJNODES_REPO", "https://github.com/kijai/ComfyUI-KJNodes.git").strip()
NODES_KJNODES_REF = os.environ.get("NODES_KJNODES_REF", "main").strip()
NODES_VHS_REPO = os.environ.get("NODES_VHS_REPO", "https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git").strip()
NODES_VHS_REF = os.environ.get("NODES_VHS_REF", "main").strip()
NODES_GGUF_REPO = os.environ.get("NODES_GGUF_REPO", "https://github.com/city96/ComfyUI-GGUF.git").strip()
NODES_GGUF_REF = os.environ.get("NODES_GGUF_REF", "main").strip()
NODES_VFI_REPO = os.environ.get("NODES_VFI_REPO", "https://github.com/Fannovel16/ComfyUI-Frame-Interpolation.git").strip()
NODES_VFI_REF = os.environ.get("NODES_VFI_REF", "main").strip()
NODES_MANAGER_REPO = os.environ.get("NODES_MANAGER_REPO", "https://github.com/ltdrdata/ComfyUI-Manager.git").strip()
NODES_MANAGER_REF = os.environ.get("NODES_MANAGER_REF", "main").strip()
NODES_RGTHREE_REPO = os.environ.get("NODES_RGTHREE_REPO", "https://github.com/rgthree/rgthree-comfy.git").strip()
NODES_RGTHREE_REF = os.environ.get("NODES_RGTHREE_REF", "main").strip()
NODES_WANSEAMLESSFLOW_REPO = os.environ.get("NODES_WANSEAMLESSFLOW_REPO", "").strip()
NODES_WANSEAMLESSFLOW_REF = os.environ.get("NODES_WANSEAMLESSFLOW_REF", "main").strip()
NODES_MMAUDIO_REPO = os.environ.get("NODES_MMAUDIO_REPO", "").strip()
NODES_MMAUDIO_REF = os.environ.get("NODES_MMAUDIO_REF", "main").strip()

NODES_FORCE_REINSTALL = os.environ.get("NODES_FORCE_REINSTALL", "0").lower() in ("1", "true", "yes", "on")
NODES_USE_ZIP_FALLBACK = os.environ.get("NODES_USE_ZIP_FALLBACK", "1").lower() in ("1", "true", "yes", "on")
NODES_PIP_INSTALL = os.environ.get("NODES_PIP_INSTALL", "1").lower() in ("1", "true", "yes", "on")
try:
    _timeout_raw = os.environ.get("NODES_TIMEOUT", "600")
    NODES_TIMEOUT = int((_timeout_raw or "600").strip())
except (TypeError, ValueError):
    NODES_TIMEOUT = 600

INSTALL_LYNX_EXTRAS = os.environ.get("INSTALL_LYNX_EXTRAS", "0").lower() in ("1", "true", "yes", "on")
LYNX_EXTRAS = [p.strip() for p in os.environ.get("LYNX_EXTRAS", "").split(",") if p.strip()]
WANSEAMLESSFLOW_APPLY_INTEGRATION = os.environ.get("WANSEAMLESSFLOW_APPLY_INTEGRATION", "0").lower() in ("1", "true", "yes", "on")
CUSTOM_NODES_DIR = (COMFY / "custom_nodes")
CUSTOM_NODES_DIR.mkdir(parents=True, exist_ok=True)

def _git_available() -> bool:
    try:
        subprocess.run(["git", "--version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        return True
    except Exception:
        return False

def _looks_like_commit(ref: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{7,40}", ref))

def _parse_github_repo(repo_url: str) -> tuple[str, str]:
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", repo_url)
    if not m:
        raise ValueError(f"Unsupported GitHub repository URL: {repo_url}")
    return m.group(1), m.group(2)

def _http_get(url: str, timeout: int | None = None):
    r = requests.get(url, timeout=timeout or NODES_TIMEOUT, stream=True)
    r.raise_for_status()
    return r

def _clone_or_update(repo_url: str, dst: Path, ref: str, force: bool) -> str:
    dst = dst.resolve()
    if force and dst.exists():
        shutil.rmtree(dst, ignore_errors=True)
    if dst.exists():
        fetch_cmd = ["git", "-C", str(dst), "fetch"]
        if not _looks_like_commit(ref):
            fetch_cmd += ["--depth", "1"]
        fetch_cmd += ["origin", ref]
        subprocess.check_call(fetch_cmd, timeout=NODES_TIMEOUT)
        subprocess.check_call(["git", "-C", str(dst), "checkout", ref], timeout=NODES_TIMEOUT)
        if not _looks_like_commit(ref):
            subprocess.check_call(["git", "-C", str(dst), "reset", "--hard", f"origin/{ref}"], timeout=NODES_TIMEOUT)
        return "updated"
    dst.parent.mkdir(parents=True, exist_ok=True)
    clone_cmd = ["git", "clone", "--depth", "1"]
    if not _looks_like_commit(ref):
        clone_cmd += ["--branch", ref]
    clone_cmd += [repo_url, str(dst)]
    subprocess.check_call(clone_cmd, timeout=NODES_TIMEOUT)
    if _looks_like_commit(ref):
        fetch_cmd = ["git", "-C", str(dst), "fetch", "origin", ref]
        subprocess.check_call(fetch_cmd, timeout=NODES_TIMEOUT)
        subprocess.check_call(["git", "-C", str(dst), "checkout", ref], timeout=NODES_TIMEOUT)
    return "cloned"

def _download_zip(repo_url: str, ref: str, dst: Path) -> str:
    owner, repo = _parse_github_repo(repo_url)
    if _looks_like_commit(ref):
        url = f"https://codeload.github.com/{owner}/{repo}/zip/{ref}"
    else:
        url = f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{ref}"
    dst = dst.resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.parent / f".{repo}.zip"
    try:
        with _http_get(url) as r, open(tmp, "wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)
        import zipfile
        with zipfile.ZipFile(tmp) as zf:
            members = zf.namelist()
            if not members:
                raise RuntimeError("zip archive empty")
            extracted_root = members[0].split("/", 1)[0]
            zf.extractall(dst.parent)
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        root = extracted_root or repo
        extracted_dir = dst.parent / root
        if not extracted_dir.exists():
            raise RuntimeError("zip extraction failed (root directory missing)")
        extracted_dir.rename(dst)
    finally:
        tmp.unlink(missing_ok=True)
    return "downloaded"

def _pip_install_requirements(node_dir: Path):
    req = node_dir / "requirements.txt"
    if req.exists() and NODES_PIP_INSTALL:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-U", "-r", str(req)], timeout=NODES_TIMEOUT)

def _dir_size(path: Path) -> int:
    if path.is_file():
        try:
            return path.stat().st_size
        except FileNotFoundError:
            return 0
    if path.is_dir():
        total = 0
        for sub in path.rglob("*"):
            if sub.is_file():
                try:
                    total += sub.stat().st_size
                except FileNotFoundError:
                    continue
        return total
    return 0

nodes_catalog = []

def _add_node(name: str, repo: str, ref: str, required: bool = False):
    if not repo:
        return
    nodes_catalog.append(dict(
        name=name, repo=repo, ref=ref or "main",
        dst=CUSTOM_NODES_DIR / name, required=required,
    ))

# 必須コア
_add_node("ComfyUI-WanVideoWrapper", NODES_WANWRAPPER_REPO, NODES_WANWRAPPER_REF, required=True)
_add_node("ComfyUI-KJNodes",         NODES_KJNODES_REPO,    NODES_KJNODES_REF,    required=True)
_add_node("ComfyUI-VideoHelperSuite", NODES_VHS_REPO,       NODES_VHS_REF,        required=True)
_add_node("ComfyUI-Manager",         NODES_MANAGER_REPO,    NODES_MANAGER_REF,    required=True)
# 推奨
_add_node("ComfyUI-GGUF",            NODES_GGUF_REPO,       NODES_GGUF_REF,       required=False)
_add_node("ComfyUI-Frame-Interpolation", NODES_VFI_REPO,    NODES_VFI_REF,        required=False)
_add_node("rgthree-comfy",           NODES_RGTHREE_REPO,    NODES_RGTHREE_REF,    required=False)
# オプション
_add_node("ComfyUI-WanSeamlessFlow", NODES_WANSEAMLESSFLOW_REPO, NODES_WANSEAMLESSFLOW_REF, required=False)
_add_node("ComfyUI-MMAudio",         NODES_MMAUDIO_REPO,    NODES_MMAUDIO_REF,    required=False)


def install_github_nodes() -> list[dict]:
    results = []
    if not INSTALL_NODES:
        print("[INFO] INSTALL_NODES=0 (skip GitHub custom nodes)")
        return results
    if not nodes_catalog:
        print("[INFO] INSTALL_NODES=1 but no repositories configured (skip)")
        return results

    have_git = _git_available()
    fallback_allowed = NODES_USE_ZIP_FALLBACK

    for entry in nodes_catalog:
        name = entry["name"]
        repo_url = entry["repo"]
        ref = entry["ref"] or "main"
        dst: Path = entry["dst"]
        rec = dict(
            source="github", kind="custom_node", name=name, repo=repo_url, ref=ref,
            local=str(dst.resolve()), required=entry.get("required", False),
            when=datetime.now(timezone.utc).isoformat(),
        )
        status = "skipped"
        method = None
        try:
            if have_git:
                status = _clone_or_update(repo_url, dst, ref, NODES_FORCE_REINSTALL)
                method = "git"
            else:
                raise RuntimeError("git not available")
        except Exception as git_exc:
            if fallback_allowed:
                print(f"[WARN] git failed for {name}: {git_exc} — trying zip fallback")
                try:
                    status = _download_zip(repo_url, ref, dst)
                    method = "zip"
                except Exception as zip_exc:
                    rec["status"] = f"error: {zip_exc}"
                    rec["method"] = method or ("git" if have_git else "zip")
                    rec["size_bytes"] = _dir_size(dst) if dst.exists() else 0
                    rec["size_GiB"] = rec["size_bytes"] / (1024**3)
                    rec["size_GBdec"] = rec["size_bytes"] / 1_000_000_000
                    rec["header_ok"] = True
                    print(f"[ERROR] Node {name}: {zip_exc}")
                    results.append(rec)
                    continue
            else:
                rec["status"] = f"error: {git_exc}"
                rec["method"] = "git"
                rec["size_bytes"] = _dir_size(dst) if dst.exists() else 0
                rec["size_GiB"] = rec["size_bytes"] / (1024**3)
                rec["size_GBdec"] = rec["size_bytes"] / 1_000_000_000
                rec["header_ok"] = True
                print(f"[ERROR] Node {name}: {git_exc}")
                results.append(rec)
                continue

        success = status in ("cloned", "updated", "downloaded")
        rec["status"] = status
        rec["method"] = method or ("git" if have_git else "zip")

        if success and NODES_PIP_INSTALL:
            try:
                _pip_install_requirements(dst)
            except Exception as pip_exc:
                rec["status"] = f"error: pip install failed ({pip_exc})"
                print(f"[ERROR] Node {name}: pip install failed — {pip_exc}")
                success = False

        if success and name == "ComfyUI-WanSeamlessFlow" and WANSEAMLESSFLOW_APPLY_INTEGRATION:
            integration_script = dst / "integration.py"
            if integration_script.exists():
                try:
                    subprocess.check_call([sys.executable, str(integration_script)], timeout=NODES_TIMEOUT)
                    print("[NODES] WanSeamlessFlow integration applied.")
                except Exception as integration_exc:
                    rec["status"] = f"error: integration failed ({integration_exc})"
                    print(f"[WARN] WanSeamlessFlow integration failed: {integration_exc}")
                    success = False

        if success and name == "ComfyUI-KJNodes":
            print("[NODES] KJNodes hint: WanImageToVideoSVIPro / PatchSageAttentionKJ etc が利用可能")
        if success and name == "ComfyUI-WanSeamlessFlow":
            print("[NODES] WanSeamlessFlow tip: SVI Pro 移行時はこちらは不要")

        size_bytes = _dir_size(dst) if dst.exists() else 0
        rec["size_bytes"] = size_bytes
        rec["size_GiB"] = size_bytes / (1024**3)
        rec["size_GBdec"] = size_bytes / 1_000_000_000
        rec["header_ok"] = True

        req_tag = " [required]" if entry.get("required") else ""
        print(f"[NODES] {name}@{ref}{req_tag} -> {rec['status']} ({rec['method']}) [{rec['local']}]")
        results.append(rec)

    if INSTALL_LYNX_EXTRAS and LYNX_EXTRAS:
        extras_rec = dict(
            source="pip", kind="lynx_extra", packages=LYNX_EXTRAS,
            when=datetime.now(timezone.utc).isoformat(),
            local="pip::" + ",".join(LYNX_EXTRAS),
            size_bytes=0, size_GiB=0.0, size_GBdec=0.0, header_ok=True,
        )
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-U"] + LYNX_EXTRAS, timeout=NODES_TIMEOUT)
            extras_rec["status"] = "installed"
            print(f"[NODES] Lynx extras installed: {', '.join(LYNX_EXTRAS)}")
        except Exception as extras_exc:
            extras_rec["status"] = f"error: {extras_exc}"
            print(f"[WARN] Lynx extras failed: {extras_exc}")
        results.append(extras_rec)

    return results

# ===== HF DL 実行 =====
manifest = []
total_target_bytes = 0
total_actual_bytes = 0
print(f"[INFO] HF download queue: {len(items)} files")

for it in items:
    repo = it["repo"]; fname = it["filename"]; dst: Path = it["dst"]
    sz_gb = it.get("size_gb_dec", 0.0)
    total_target_bytes += int(sz_gb * 1_000_000_000) if sz_gb else 0
    if dst.exists() and not FORCE_REDOWNLOAD:
        actual = dst.stat().st_size
        total_actual_bytes += actual
        manifest.append(dict(
            source="huggingface", kind="model", repo=repo, filename=fname,
            local=str(dst), status="exists", size_bytes=actual,
            size_GiB=actual/(1024**3), size_GBdec=actual/1_000_000_000,
            header_ok=validate_safetensors_header(dst) if dst.suffix == ".safetensors" else True,
            when=datetime.now(timezone.utc).isoformat(),
        ))
        print(f"[SKIP] {dst.name} (exists, {actual/1_000_000_000:.2f}GB)")
        continue
    print(f"[DL] {repo}/{fname} -> {dst.name} (~{sz_gb:.2f}GB)")
    try:
        local = hf_hub_download(repo_id=repo, filename=fname, local_dir=str(dst.parent), token=HF_TOKEN, force_download=FORCE_REDOWNLOAD)
        local_p = Path(local)
        if local_p.resolve() != dst.resolve():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(local_p), str(dst))
        actual = dst.stat().st_size
        total_actual_bytes += actual
        ok = validate_safetensors_header(dst) if dst.suffix == ".safetensors" else True
        manifest.append(dict(
            source="huggingface", kind="model", repo=repo, filename=fname,
            local=str(dst), status="downloaded", size_bytes=actual,
            size_GiB=actual/(1024**3), size_GBdec=actual/1_000_000_000,
            header_ok=ok, when=datetime.now(timezone.utc).isoformat(),
        ))
        print(f"[OK] {dst.name} ({actual/1_000_000_000:.2f}GB) header_ok={ok}")
    except Exception as e:
        manifest.append(dict(
            source="huggingface", kind="model", repo=repo, filename=fname,
            local=str(dst), status=f"error: {e}", size_bytes=0,
            size_GiB=0.0, size_GBdec=0.0, header_ok=False,
            when=datetime.now(timezone.utc).isoformat(),
        ))
        print(f"[ERROR] {repo}/{fname}: {e}")

# ===== カスタムノード DL =====
node_results = install_github_nodes()
manifest.extend(node_results)

# ============================================================
# ===== CivitAI Robust Downloader (v6 で統合) =====
# ============================================================
# 旧 civitai_robust.py の実装をここに統合。
# 対応する失敗パターン:
#   - civitai.com → civitai.red に移行したモデル (404)
#   - DL URL の S3 リダイレクト時の Authorization 消失
#   - API 経由で取れた DL URL が 403 を返す場合の直叩き fallback
#   - Early Access の 403 検出と明示的なメッセージ
#   - token 問題 (401) の明示的なメッセージ
#   - aria2c / requests 両対応 + aria2c 失敗時の requests fallback
# ============================================================

def _civitai_parse_version_id(s: str) -> Optional[str]:
    """URL / ID / 混在文字列から modelVersionId を抽出"""
    s = s.strip()
    if not s:
        return None
    if s.isdigit():
        return s
    patterns = [
        r"[?&]modelVersionId=(\d+)",
        r"/api/download/models/(\d+)",
        r"/api/v1/model-versions/(\d+)",
        r"/model-versions/(\d+)",
    ]
    for pat in patterns:
        m = re.search(pat, s)
        if m:
            return m.group(1)
    return None


def _civitai_auth(token: Optional[str]) -> Tuple[dict, dict]:
    headers = {}
    params = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        params["token"] = token
    return headers, params


def _civitai_status_reason(status: int, body_preview: str = "") -> str:
    body_lower = body_preview.lower() if body_preview else ""
    if status == 401:
        return "認証失敗 (token 無効 or 期限切れ or revoke)"
    if status == 403:
        if "early access" in body_lower or "supporter" in body_lower:
            return "Early Access 期間中 (有料 supporter のみ DL 可) / or 地域制限"
        return "アクセス禁止 (Early Access / 規約違反 / 地域制限のいずれか)"
    if status == 404:
        return "モデルが見つからない (civitai.com → civitai.red に移行済みの可能性 / or 削除済み)"
    if status == 429:
        return "レート制限"
    if 500 <= status < 600:
        return f"サーバエラー ({status})"
    return f"HTTP {status}"


def _civitai_fetch_meta(version_id: str, token: Optional[str]) -> Tuple[Optional[dict], str]:
    """civitai.com → civitai.red の順（または逆順）で API を叩いて version メタ情報取得"""
    headers, params = _civitai_auth(token)
    errors = []
    for domain in CIVITAI_DOMAINS:
        url = f"https://{domain}/api/v1/model-versions/{version_id}"
        try:
            r = requests.get(url, params=params, headers=headers, timeout=CIVITAI_REQUEST_TIMEOUT)
            if r.status_code == 200:
                meta = r.json()
                meta["_resolved_domain"] = domain
                return meta, ""
            else:
                body_preview = (r.text or "")[:200]
                reason = _civitai_status_reason(r.status_code, body_preview)
                errors.append(f"  {domain}: HTTP {r.status_code} - {reason}")
                if r.status_code == 401:
                    break  # 全ドメインで同じく失敗するはず
        except requests.RequestException as e:
            errors.append(f"  {domain}: {type(e).__name__}: {e}")
    return None, "API 失敗:\n" + "\n".join(errors)


def _civitai_select_best_file(files: list, only_safetensors: bool = True) -> Optional[dict]:
    if only_safetensors:
        files = [f for f in files if (f.get("name") or "").lower().endswith(".safetensors")]
    if not files:
        return None
    files = sorted(files, key=lambda f: (0 if f.get("primary") else 1, -(f.get("sizeKB") or 0)))
    return files[0]


def _civitai_build_urls(meta: dict, chosen_file: dict, version_id: str) -> list:
    """試すべき DL URL を複数パターン生成"""
    urls = []
    # 1. API から取れた DL URL を最優先
    api_url = chosen_file.get("downloadUrl")
    if api_url:
        urls.append(api_url)
        for d1, d2 in [("civitai.com", "civitai.red"), ("civitai.red", "civitai.com")]:
            if f"://{d1}/" in api_url:
                urls.append(api_url.replace(f"://{d1}/", f"://{d2}/"))
    # 2. 直接パターン
    for domain in CIVITAI_DOMAINS:
        direct = f"https://{domain}/api/download/models/{version_id}"
        if direct not in urls:
            urls.append(direct)
    # 3. file id 指定パターン
    file_id = chosen_file.get("id")
    if file_id:
        for domain in CIVITAI_DOMAINS:
            with_fid = f"https://{domain}/api/download/models/{version_id}?type=Model&format=SafeTensor&fileId={file_id}"
            if with_fid not in urls:
                urls.append(with_fid)
    return urls


def _civitai_dl_requests(url: str, out_path: Path, token: Optional[str]) -> Tuple[bool, str]:
    headers, params = _civitai_auth(token)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".part")
    try:
        with requests.get(url, params=params, headers=headers,
                          stream=True, timeout=CIVITAI_DL_TIMEOUT, allow_redirects=True) as r:
            if r.status_code != 200:
                body_preview = (r.text or "")[:200]
                reason = _civitai_status_reason(r.status_code, body_preview)
                return False, f"HTTP {r.status_code} - {reason}"
            ct = r.headers.get("Content-Type", "").lower()
            if "html" in ct or "json" in ct:
                preview = r.content[:200].decode("utf-8", errors="replace")
                return False, f"Unexpected Content-Type: {ct} / body: {preview}"
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1024 * 1024):
                    if chunk:
                        f.write(chunk)
        tmp.rename(out_path)
        return True, ""
    except requests.RequestException as e:
        tmp.unlink(missing_ok=True)
        return False, f"{type(e).__name__}: {e}"


def _civitai_dl_aria2c(url: str, out_path: Path, token: Optional[str]) -> Tuple[bool, str]:
    if not _which("aria2c"):
        return False, "aria2c not installed"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # 重要: token は URL query で渡すのみ。
    #       --header "Authorization: Bearer xxx" を付けると aria2c が
    #       S3 リダイレクト先にも同じ header を送ってしまい、S3 が拒否して
    #       rc=22 で失敗する。query token なら CivitAI 側だけで認証され、
    #       S3 への redirect URL は signed なのでそのまま通る。
    if token and "token=" not in url:
        sep = "&" if "?" in url else "?"
        url_with_token = f"{url}{sep}token={token}"
    else:
        url_with_token = url
    cmd = [
        "aria2c", "-x", "16", "-s", "16", "-c",
        "--auto-file-renaming=false", "--allow-overwrite=true",
        "--max-tries=3", "--retry-wait=2",
        "-d", str(out_path.parent), "-o", out_path.name, url_with_token,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=CIVITAI_DL_TIMEOUT)
        if r.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0:
            return True, ""
        err = (r.stderr or r.stdout or "")[-500:]
        return False, f"aria2c rc={r.returncode}: {err}"
    except subprocess.TimeoutExpired:
        return False, "aria2c timeout"
    except Exception as e:
        return False, f"aria2c error: {e}"


def civitai_download_robust(version_id: str) -> dict:
    """指定 modelVersionId を robust に DL し、manifest 互換 dict を返す"""
    token = CIVITAI_TOKEN or None
    prefer_aria2c = USE_ARIA2C
    only_safetensors = CIVITAI_ONLY_SAFETENSORS
    force = CIVITAI_FORCE_REDOWNLOAD

    base_rec = dict(
        source="civitai", kind="lora", model_version_id=version_id,
        when=datetime.now(timezone.utc).isoformat(),
        size_bytes=0, size_GiB=0.0, size_GBdec=0.0, header_ok=False,
        attempts=[],
    )

    # Step 1: API メタ取得
    meta, api_err = _civitai_fetch_meta(version_id, token)
    if meta is None:
        base_rec["status"] = f"error: api_fetch_failed\n{api_err}"
        base_rec["attempts"].append({"phase": "api", "error": api_err})
        return base_rec

    base_rec["attempts"].append({
        "phase": "api",
        "domain": meta.get("_resolved_domain"),
        "status": "ok",
    })

    # Step 2: ファイル選択
    files = meta.get("files") or []
    chosen = _civitai_select_best_file(files, only_safetensors=only_safetensors)
    if not chosen:
        base_rec["status"] = f"error: no suitable file (safetensors={only_safetensors})"
        return base_rec

    filename = chosen.get("name") or f"civitai_{version_id}.safetensors"
    out_path = LOR / filename
    expected_sz = (chosen.get("sizeKB") or 0) * 1024

    # Step 3: 既存チェック
    if out_path.exists() and not force:
        actual = out_path.stat().st_size
        ok = validate_safetensors_header(out_path)
        base_rec["status"] = "exists"
        base_rec["local"] = str(out_path)
        base_rec["size_bytes"] = actual
        base_rec["size_GiB"] = actual / (1024**3)
        base_rec["size_GBdec"] = actual / 1_000_000_000
        base_rec["header_ok"] = ok
        print(f"[SKIP] CivitAI {filename} (exists, {actual/1_000_000_000:.2f}GB)")
        return base_rec

    # Step 4: DL URL 候補を生成して順次試行
    urls = _civitai_build_urls(meta, chosen, version_id)
    base_rec["attempts"].append({"phase": "url_build", "count": len(urls)})

    print(f"[DL] CivitAI {filename} (~{expected_sz/1_000_000_000:.2f}GB, {len(urls)} URL候補)")

    for i, url in enumerate(urls, 1):
        method = "aria2c" if (prefer_aria2c and _which("aria2c")) else "requests"
        print(f"  [try {i}/{len(urls)}] {method}: {url[:120]}...")

        if method == "aria2c":
            ok, err = _civitai_dl_aria2c(url, out_path, token)
        else:
            ok, err = _civitai_dl_requests(url, out_path, token)

        attempt = {"phase": "download", "url": url, "method": method}
        if ok:
            actual = out_path.stat().st_size
            header_ok = validate_safetensors_header(out_path)
            base_rec["status"] = "downloaded"
            base_rec["local"] = str(out_path)
            base_rec["size_bytes"] = actual
            base_rec["size_GiB"] = actual / (1024**3)
            base_rec["size_GBdec"] = actual / 1_000_000_000
            base_rec["header_ok"] = header_ok
            attempt["status"] = "ok"
            attempt["size_bytes"] = actual
            base_rec["attempts"].append(attempt)
            print(f"  ✓ OK: {filename} ({actual/1_000_000_000:.2f}GB) header_ok={header_ok}")
            return base_rec

        print(f"    ✗ {err}")
        attempt["error"] = err
        base_rec["attempts"].append(attempt)

        # aria2c 失敗時は requests でも 1 回試す
        if method == "aria2c":
            ok2, err2 = _civitai_dl_requests(url, out_path, token)
            attempt2 = {"phase": "download", "url": url, "method": "requests (fallback)"}
            if ok2:
                actual = out_path.stat().st_size
                header_ok = validate_safetensors_header(out_path)
                base_rec["status"] = "downloaded"
                base_rec["local"] = str(out_path)
                base_rec["size_bytes"] = actual
                base_rec["size_GiB"] = actual / (1024**3)
                base_rec["size_GBdec"] = actual / 1_000_000_000
                base_rec["header_ok"] = header_ok
                attempt2["status"] = "ok"
                attempt2["size_bytes"] = actual
                base_rec["attempts"].append(attempt2)
                print(f"  ✓ OK (fallback requests): {filename} ({actual/1_000_000_000:.2f}GB)")
                return base_rec
            print(f"    ✗ fallback: {err2}")
            attempt2["error"] = err2
            base_rec["attempts"].append(attempt2)

    # 全試行失敗
    last_errors = [a.get("error", "") for a in base_rec["attempts"] if a.get("phase") == "download"]
    base_rec["status"] = (
        f"error: all {len(urls)} URLs failed\n  last errors:\n  - "
        + "\n  - ".join(last_errors[-3:])
    )
    base_rec["local"] = str(out_path)
    return base_rec


# ===== CivitAI 実行 =====
CIVITAI_VERSIONS = [v.strip() for v in os.environ.get("CIVITAI_VERSIONS", "").split(",") if v.strip()]
if CIVITAI_VERSIONS:
    print(f"[INFO] CivitAI queue: {len(CIVITAI_VERSIONS)} versions (domain order: {CIVITAI_DOMAINS})")
    if not CIVITAI_TOKEN:
        print("[WARN] CIVITAI_TOKEN が空。NSFW / 会員限定モデルは取れません。")
    for raw in CIVITAI_VERSIONS:
        vid = _civitai_parse_version_id(raw)
        if not vid:
            print(f"[WARN] Cannot parse CivitAI version: {raw}")
            continue
        print(f"=== CivitAI version_id={vid} ===")
        rec = civitai_download_robust(vid)
        manifest.append(rec)
        if rec["status"].startswith("error"):
            print(f"[ERROR] CivitAI {vid}: {rec['status']}")
        else:
            print(f"[OK] CivitAI {vid}: {rec['status']}")

# ===== 結果出力 =====
out_manifest = COMFY / "models" / "_download_manifest_v6.jsonl"
out_manifest.parent.mkdir(parents=True, exist_ok=True)
with open(out_manifest, "w", encoding="utf-8") as f:
    for rec in manifest:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
print(f"[INFO] Manifest written: {out_manifest} ({len(manifest)} entries)")

# 集計
ok_count = sum(1 for r in manifest if r.get("status") in ("downloaded", "exists", "cloned", "updated", "installed"))
err_count = sum(1 for r in manifest if str(r.get("status", "")).startswith("error"))
total_size = sum(r.get("size_bytes", 0) for r in manifest)
print(f"[SUMMARY] OK={ok_count} ERROR={err_count} TOTAL_SIZE={total_size/1_000_000_000:.1f}GB")

if err_count:
    print("[SUMMARY] Some downloads failed. Check manifest for details.")
    print("[HINT] CivitAI 401 → CIVITAI_TOKEN 設定")
    print("[HINT] CivitAI 404 全ドメイン失敗 → モデル削除済み or version_id 間違い")
    print("[HINT] CivitAI 403 (Early Access) → supporter 期間明けまで待機")
    print("[HINT] CivitAI NSFW モデルが取れない → CIVITAI_DOMAIN_PREFER=red を試す")
    print("[HINT] HF 403/404 → repo 名/ファイル名変更の可能性、最新化要")
    print("[HINT] rCM repo は research 寄りなので構造変動あり、要 https://github.com/thu-ml/TurboDiffusion 確認")
