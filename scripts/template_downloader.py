#!/usr/bin/env python3
"""Manifest-driven downloader for the lightweight Wan/ComfyUI template."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _parse_settings_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            for lineno, raw in enumerate(handle, 1):
                line = raw.strip()
                if not line or line.startswith(("#", ";")):
                    continue
                if "=" not in line:
                    print(f"[WARN] settings line {lineno} ignored (missing '='): {raw.rstrip()}")
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                    value = value[1:-1]
                values[key] = os.path.expandvars(os.path.expanduser(value))
    except FileNotFoundError:
        return {}
    return values


def _default_settings_path() -> Path:
    return (Path(__file__).resolve().parent.parent / "config" / "settings" / "workflow_bundle.env").resolve()


def _resolve_template_path(path: Path) -> Path:
    candidate = path.expanduser()
    repo_root = Path(__file__).resolve().parent.parent
    config_root = (repo_root / "config").resolve()
    if candidate.exists():
        return candidate.resolve()
    if not candidate.is_absolute():
        cwd_candidate = (Path.cwd() / candidate).resolve()
        if cwd_candidate.exists():
            return cwd_candidate
        repo_candidate = (repo_root / candidate).resolve()
        if repo_candidate.exists():
            return repo_candidate
        return candidate.resolve()
    parts = candidate.parts
    if len(parts) >= 3 and parts[1] == "opt" and parts[2] == "template-config":
        local_candidate = config_root.joinpath(*parts[3:])
        if local_candidate.exists():
            return local_candidate.resolve()
    return candidate.resolve()


def _load_settings_env(path: Path | None) -> Path:
    resolved = path or Path(os.environ.get("DOWNLOADER_SETTINGS_PATH", str(_default_settings_path()))).expanduser()
    resolved = _resolve_template_path(resolved)
    loaded = _parse_settings_file(resolved)
    if loaded:
        os.environ.update(loaded)
        print(f"[INFO] Loaded {len(loaded)} settings from {resolved}")
    else:
        print(f"[INFO] Settings file not found or empty: {resolved}")
    return resolved


def _strtobool(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


ARGS = argparse.ArgumentParser()
ARGS.add_argument("--settings", type=Path, help="KEY=VALUE settings file")
ARGS.add_argument("--phase", choices=("all", "nodes", "models"), default="all")
ARGS.add_argument("--hf-manifest", type=Path, help="Path to the Hugging Face/direct model manifest")
ARGS.add_argument("--node-manifest", type=Path, help="Path to the custom node manifest")
CLI = ARGS.parse_args()

SETTINGS_PATH = _load_settings_env(CLI.settings)

USE_HF_TRANSFER = _strtobool("USE_HF_TRANSFER")
ALLOW_RUNTIME_PIP_INSTALL = _strtobool("ALLOW_RUNTIME_PIP_INSTALL")
FORCE_REDOWNLOAD = _strtobool("FORCE_REDOWNLOAD")
INSTALL_NODES = _strtobool("INSTALL_NODES", "1")
NODES_FORCE_REINSTALL = _strtobool("NODES_FORCE_REINSTALL")
NODES_USE_ZIP_FALLBACK = _strtobool("NODES_USE_ZIP_FALLBACK", "1")
NODES_PIP_INSTALL = _strtobool("NODES_PIP_INSTALL", "1")
CIVITAI_FORCE_REDOWNLOAD = _strtobool("CIVITAI_FORCE_REDOWNLOAD")
CIVITAI_ONLY_SAFETENSORS = _strtobool("CIVITAI_ONLY_SAFETENSORS", "1")
DIRECT_USE_ARIA2 = _strtobool("DIRECT_USE_ARIA2", "1")
HF_MAX_WORKERS = max(1, int(os.environ.get("HF_MAX_WORKERS", "4")))
DIRECT_MAX_WORKERS = max(1, int(os.environ.get("DIRECT_MAX_WORKERS", "2")))
NODES_TIMEOUT = int(os.environ.get("NODES_TIMEOUT", "900"))
CIVITAI_REQUEST_TIMEOUT = int(os.environ.get("CIVITAI_REQUEST_TIMEOUT", "60"))
CIVITAI_DL_TIMEOUT = int(os.environ.get("CIVITAI_DL_TIMEOUT", "900"))
COMFY_BASE = Path(os.environ.get("COMFYUI_BASE", "/workspace/ComfyUI")).expanduser().resolve()
HF_TOKEN = os.environ.get("HF_TOKEN", "").strip() or None
CIVITAI_TOKEN = os.environ.get("CIVITAI_TOKEN", "").strip() or None
MODEL_INCLUDE_GROUPS = set(_split_csv(os.environ.get("ENABLED_MODEL_GROUPS")))
MODEL_EXCLUDE_GROUPS = set(_split_csv(os.environ.get("DISABLED_MODEL_GROUPS")))
NODE_INCLUDE_GROUPS = set(_split_csv(os.environ.get("ENABLED_NODE_GROUPS")))
NODE_EXCLUDE_GROUPS = set(_split_csv(os.environ.get("DISABLED_NODE_GROUPS")))
CIVITAI_VERSIONS = _split_csv(os.environ.get("CIVITAI_VERSIONS"))
CIVITAI_QUEUE_PATH = os.environ.get("CIVITAI_QUEUE_PATH", "").strip()
CIVITAI_DEFAULT_TARGET_DIR = os.environ.get("CIVITAI_DEFAULT_TARGET_DIR", "loras").strip() or "loras"
CIVITAI_DEFAULT_SUBDIR = os.environ.get("CIVITAI_DEFAULT_SUBDIR", "").strip().strip("/")
DOMAIN_PREFER = os.environ.get("CIVITAI_DOMAIN_PREFER", "com").strip().lower()
CIVITAI_DOMAINS = ["civitai.red", "civitai.com"] if DOMAIN_PREFER == "red" else ["civitai.com", "civitai.red"]


def _ensure(pkgs: list[str]) -> None:
    import importlib.util

    missing = [pkg for pkg in pkgs if importlib.util.find_spec(pkg.split("[")[0]) is None]
    if not missing:
        return
    if not ALLOW_RUNTIME_PIP_INSTALL:
        missing_str = ", ".join(missing)
        raise RuntimeError(
            f"Missing Python packages: {missing_str}. "
            "Install them in the image/venv first, or set ALLOW_RUNTIME_PIP_INSTALL=1."
        )
    cmd = [sys.executable, "-m", "pip", "install", "-U", *missing]
    if USE_HF_TRANSFER and "huggingface_hub" in missing:
        cmd = [sys.executable, "-m", "pip", "install", "-U", "huggingface_hub[hf_transfer]", *[m for m in missing if m != "huggingface_hub"]]
    subprocess.check_call(cmd)


_ensure(["requests", "huggingface_hub"])

import requests
from huggingface_hub import hf_hub_download

if USE_HF_TRANSFER:
    os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"

MODEL_ROOTS = {
    "diffusion_models": COMFY_BASE / "models" / "diffusion_models",
    "text_encoders": COMFY_BASE / "models" / "text_encoders",
    "loras": COMFY_BASE / "models" / "loras",
    "vae": COMFY_BASE / "models" / "vae",
    "clip_vision": COMFY_BASE / "models" / "clip_vision",
    "unet": COMFY_BASE / "models" / "unet",
    "upscale_models": COMFY_BASE / "models" / "upscale_models",
    "detection": COMFY_BASE / "models" / "detection",
}
CUSTOM_NODES_DIR = COMFY_BASE / "custom_nodes"
for directory in [*MODEL_ROOTS.values(), CUSTOM_NODES_DIR]:
    directory.mkdir(parents=True, exist_ok=True)


def _which(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def validate_safetensors_header(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            head = handle.read(8)
            if len(head) < 8:
                return False
            import struct

            (header_size,) = struct.unpack("<Q", head)
            if header_size <= 0 or header_size > 100 * 1024 * 1024:
                return False
            handle.seek(8 + header_size)
            return True
    except Exception:
        return False


def _load_manifest(path: Path, root_keys: tuple[str, ...]) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [entry for entry in payload if isinstance(entry, dict)]
    for key in root_keys:
        values = payload.get(key)
        if isinstance(values, list):
            return [entry for entry in values if isinstance(entry, dict)]
    raise ValueError(f"Unsupported manifest shape for {path}")


def _select_by_groups(item: dict[str, Any], include: set[str], exclude: set[str]) -> bool:
    if item.get("enabled", True) is False:
        return False
    groups = set(item.get("groups") or [])
    if include and not (groups & include):
        return False
    if exclude and groups & exclude:
        return False
    return True


def _resolve_model_parent(target_dir: str) -> Path:
    normalized = target_dir.strip().strip("/")
    if not normalized:
        raise ValueError("target_dir cannot be empty")
    if normalized in MODEL_ROOTS:
        parent = MODEL_ROOTS[normalized]
    else:
        target_path = Path(normalized)
        root_key = target_path.parts[0] if target_path.parts else ""
        if root_key in MODEL_ROOTS:
            parent = MODEL_ROOTS[root_key].joinpath(*target_path.parts[1:])
        else:
            parent = COMFY_BASE / target_path
    parent.mkdir(parents=True, exist_ok=True)
    return parent


def _resolve_target(item: dict[str, Any]) -> Path:
    if item.get("target_path"):
        target = Path(item["target_path"])
        return target if target.is_absolute() else COMFY_BASE / target
    target_dir = item.get("target_dir")
    if not target_dir:
        raise ValueError(f"Manifest item is missing target_dir/target_path: {item}")
    parent = _resolve_model_parent(str(target_dir))
    target_name = item.get("target_name") or Path(item.get("filename") or item.get("url", "").split("?")[0]).name
    if not target_name:
        raise ValueError(f"Manifest item is missing target_name/filename/url: {item}")
    return parent / target_name


def _clone_or_update(repo_url: str, dst: Path, ref: str, force: bool) -> str:
    dst = dst.resolve()
    if force and dst.exists():
        shutil.rmtree(dst, ignore_errors=True)
    if dst.exists():
        git_dir = dst / ".git"
        if git_dir.exists():
            try:
                current = subprocess.check_output(
                    ["git", "-C", str(dst), "rev-parse", "HEAD"],
                    text=True,
                    timeout=NODES_TIMEOUT,
                ).strip()
                if current == ref:
                    return "exists"
            except Exception:
                pass
        subprocess.check_call(["git", "-C", str(dst), "fetch", "--depth", "1", "origin", ref], timeout=NODES_TIMEOUT)
        subprocess.check_call(["git", "-C", str(dst), "checkout", "--force", "FETCH_HEAD"], timeout=NODES_TIMEOUT)
        return "updated"
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(["git", "clone", "--depth", "1", repo_url, str(dst)], timeout=NODES_TIMEOUT)
    subprocess.check_call(["git", "-C", str(dst), "fetch", "--depth", "1", "origin", ref], timeout=NODES_TIMEOUT)
    subprocess.check_call(["git", "-C", str(dst), "checkout", "--force", "FETCH_HEAD"], timeout=NODES_TIMEOUT)
    return "cloned"


def _download_zip(repo_url: str, ref: str, dst: Path) -> str:
    match = re.match(r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", repo_url)
    if not match:
        raise ValueError(f"Unsupported GitHub URL: {repo_url}")
    owner, repo = match.group(1), match.group(2)
    url = f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{ref}"
    tmp = dst.parent / f".{repo}.zip"
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        with requests.get(url, timeout=NODES_TIMEOUT, stream=True) as response:
            response.raise_for_status()
            with tmp.open("wb") as handle:
                for chunk in response.iter_content(1024 * 1024):
                    if chunk:
                        handle.write(chunk)
        import zipfile

        with zipfile.ZipFile(tmp) as archive:
            members = archive.namelist()
            if not members:
                raise RuntimeError("zip archive is empty")
            root = members[0].split("/", 1)[0]
            archive.extractall(dst.parent)
        extracted = dst.parent / root
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        extracted.rename(dst)
        return "downloaded"
    finally:
        tmp.unlink(missing_ok=True)


def _pip_install_requirements(node_dir: Path, entry: dict[str, Any]) -> None:
    requirements_file = str(entry.get("requirements_file", "requirements.txt") or "").strip()
    if requirements_file and NODES_PIP_INSTALL:
        req = node_dir / requirements_file
        if req.exists():
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "--no-build-isolation", "-U", "-r", str(req)],
                timeout=NODES_TIMEOUT,
            )
    install_policy = str(entry.get("install_py_policy", "run")).strip().lower()
    install_py = node_dir / "install.py"
    if not install_py.exists() or install_policy == "skip":
        return
    try:
        subprocess.check_call([sys.executable, str(install_py)], timeout=NODES_TIMEOUT)
    except Exception:
        if install_policy == "best_effort":
            print(f"[WARN] install.py failed for {node_dir.name}; continuing because install_py_policy=best_effort")
            return
        raise


def _dir_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except FileNotFoundError:
                continue
    return total


def install_nodes(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if not INSTALL_NODES:
        print("[INFO] INSTALL_NODES=0 -> skipping custom node installation")
        return results
    for entry in entries:
        if not _select_by_groups(entry, NODE_INCLUDE_GROUPS, NODE_EXCLUDE_GROUPS):
            continue
        name = entry["name"]
        repo_url = entry["repo"]
        ref = entry.get("ref", "main")
        dst = CUSTOM_NODES_DIR / name
        record: dict[str, Any] = {
            "source": "github",
            "kind": "custom_node",
            "id": entry.get("id", name),
            "name": name,
            "repo": repo_url,
            "ref": ref,
            "groups": entry.get("groups", []),
            "local": str(dst),
            "when": datetime.now(timezone.utc).isoformat(),
        }
        try:
            if _which("git"):
                status = _clone_or_update(repo_url, dst, ref, NODES_FORCE_REINSTALL)
                method = "git"
            elif NODES_USE_ZIP_FALLBACK:
                status = _download_zip(repo_url, ref, dst)
                method = "zip"
            else:
                raise RuntimeError("git not available and zip fallback disabled")
            if entry.get("pip_install", True):
                _pip_install_requirements(dst, entry)
            size_bytes = _dir_size(dst)
            record.update(
                status=status,
                method=method,
                size_bytes=size_bytes,
                size_GiB=size_bytes / (1024**3),
                size_GBdec=size_bytes / 1_000_000_000,
                header_ok=True,
            )
            print(f"[NODES] {name}@{ref} -> {status} ({method})")
        except Exception as exc:
            size_bytes = _dir_size(dst) if dst.exists() else 0
            record.update(
                status=f"error: {exc}",
                method="git" if _which("git") else "zip",
                size_bytes=size_bytes,
                size_GiB=size_bytes / (1024**3),
                size_GBdec=size_bytes / 1_000_000_000,
                header_ok=False,
            )
            print(f"[ERROR] Node {name}: {exc}")
        results.append(record)
    return results


def _model_record_base(item: dict[str, Any], target: Path) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "source": item.get("source", "huggingface"),
        "kind": "model",
        "repo": item.get("repo"),
        "url": item.get("url"),
        "filename": item.get("filename"),
        "groups": item.get("groups", []),
        "local": str(target),
        "when": datetime.now(timezone.utc).isoformat(),
    }


def _direct_download_requests(url: str, target: Path, timeout: int = 900) -> tuple[bool, str]:
    tmp = target.with_suffix(target.suffix + ".part")
    try:
        with requests.get(url, stream=True, timeout=timeout, allow_redirects=True) as response:
            response.raise_for_status()
            with tmp.open("wb") as handle:
                for chunk in response.iter_content(1024 * 1024):
                    if chunk:
                        handle.write(chunk)
        tmp.rename(target)
        return True, ""
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        return False, str(exc)


def _direct_download_aria2(url: str, target: Path, timeout: int = 900) -> tuple[bool, str]:
    if not _which("aria2c"):
        return False, "aria2c not installed"
    cmd = [
        "aria2c",
        "-x",
        "8",
        "-s",
        "8",
        "-c",
        "--auto-file-renaming=false",
        "--allow-overwrite=true",
        "-d",
        str(target.parent),
        "-o",
        target.name,
        url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0 and target.exists() and target.stat().st_size > 0:
            return True, ""
        return False, (result.stderr or result.stdout or "").strip()[-400:]
    except Exception as exc:
        return False, str(exc)


def _download_one_model(item: dict[str, Any]) -> dict[str, Any]:
    target = _resolve_target(item)
    target.parent.mkdir(parents=True, exist_ok=True)
    record = _model_record_base(item, target)
    if target.exists() and not FORCE_REDOWNLOAD:
        size_bytes = target.stat().st_size
        record.update(
            status="exists",
            size_bytes=size_bytes,
            size_GiB=size_bytes / (1024**3),
            size_GBdec=size_bytes / 1_000_000_000,
            header_ok=validate_safetensors_header(target) if target.suffix == ".safetensors" else True,
        )
        return record

    source = item.get("source", "huggingface")
    try:
        if source == "huggingface":
            local = Path(
                hf_hub_download(
                    repo_id=item["repo"],
                    filename=item["filename"],
                    local_dir=str(target.parent),
                    token=HF_TOKEN,
                    force_download=FORCE_REDOWNLOAD,
                )
            )
            if local.resolve() != target.resolve():
                shutil.move(str(local), str(target))
        elif source == "direct":
            url = item["url"]
            method = "aria2c" if DIRECT_USE_ARIA2 and _which("aria2c") else "requests"
            ok, err = _direct_download_aria2(url, target) if method == "aria2c" else _direct_download_requests(url, target)
            if not ok and method == "aria2c":
                ok, err = _direct_download_requests(url, target)
            if not ok:
                raise RuntimeError(err)
        else:
            raise ValueError(f"Unsupported source: {source}")

        size_bytes = target.stat().st_size
        record.update(
            status="downloaded",
            size_bytes=size_bytes,
            size_GiB=size_bytes / (1024**3),
            size_GBdec=size_bytes / 1_000_000_000,
            header_ok=validate_safetensors_header(target) if target.suffix == ".safetensors" else True,
        )
        return record
    except Exception as exc:
        record.update(status=f"error: {exc}", size_bytes=0, size_GiB=0.0, size_GBdec=0.0, header_ok=False)
        return record


def download_models(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = [entry for entry in entries if _select_by_groups(entry, MODEL_INCLUDE_GROUPS, MODEL_EXCLUDE_GROUPS)]
    if not selected:
        print("[INFO] No model entries matched the current group filters")
        return []

    hf_items = [entry for entry in selected if entry.get("source", "huggingface") == "huggingface"]
    direct_items = [entry for entry in selected if entry.get("source") == "direct"]
    results: list[dict[str, Any]] = []

    def _run_pool(items: list[dict[str, Any]], workers: int) -> None:
        if not items:
            return
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_download_one_model, item): item for item in items}
            for future in as_completed(futures):
                record = future.result()
                results.append(record)
                print(f"[MODELS] {record['id']}: {record['status']}")

    _run_pool(hf_items, HF_MAX_WORKERS)
    _run_pool(direct_items, DIRECT_MAX_WORKERS)
    return sorted(results, key=lambda entry: entry.get("id") or "")


def _civitai_parse_version_id(raw: str) -> str | None:
    value = raw.strip()
    if value.isdigit():
        return value
    patterns = [
        r"[?&]modelVersionId=(\d+)",
        r"/api/download/models/(\d+)",
        r"/api/v1/model-versions/(\d+)",
        r"/model-versions/(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, value)
        if match:
            return match.group(1)
    return None


def _load_civitai_queue(path: Path) -> list[Any]:
    if not path.exists():
        print(f"[INFO] CivitAI queue file not found: {path}")
        return []
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("items", "civitai", "versions", "downloads"):
                values = payload.get(key)
                if isinstance(values, list):
                    return values
            return [payload]
        raise ValueError(f"Unsupported JSON payload in {path}")

    entries: list[Any] = []
    with path.open("r", encoding="utf-8") as handle:
        for lineno, raw in enumerate(handle, 1):
            line = raw.strip()
            if not line or line.startswith(("#", ";")):
                continue
            if line.startswith("{"):
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSON line at {path}:{lineno}: {exc}") from exc
            else:
                entries.append(line)
    return entries


def _normalize_civitai_entry(raw: Any, origin: str) -> dict[str, Any] | None:
    if isinstance(raw, str):
        source_input = raw.strip()
        if not source_input:
            return None
        entry: dict[str, Any] = {"source_input": source_input}
    elif isinstance(raw, dict):
        if raw.get("enabled", True) is False:
            return None
        entry = dict(raw)
        source_input = str(
            entry.get("source_input")
            or entry.get("version_id")
            or entry.get("modelVersionId")
            or entry.get("url")
            or entry.get("value")
            or entry.get("id")
            or ""
        ).strip()
        entry["source_input"] = source_input
    else:
        raise ValueError(f"Unsupported CivitAI queue entry from {origin}: {raw!r}")

    subdir = str(entry.get("subdir") or CIVITAI_DEFAULT_SUBDIR or "").strip().strip("/")
    target_dir = str(entry.get("target_dir") or CIVITAI_DEFAULT_TARGET_DIR or "loras").strip().strip("/")
    if subdir:
        target_dir = str(Path(target_dir) / subdir)

    entry["version_id"] = _civitai_parse_version_id(entry["source_input"])
    entry["kind"] = str(entry.get("kind") or "lora")
    entry["target_dir"] = target_dir
    entry["queue_origin"] = origin
    return entry


def _collect_civitai_entries() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for raw in CIVITAI_VERSIONS:
        normalized = _normalize_civitai_entry(raw, "env:CIVITAI_VERSIONS")
        if normalized:
            entries.append(normalized)
    if CIVITAI_QUEUE_PATH:
        queue_path = _resolve_template_path(Path(CIVITAI_QUEUE_PATH))
        for raw in _load_civitai_queue(queue_path):
            normalized = _normalize_civitai_entry(raw, f"file:{queue_path}")
            if normalized:
                entries.append(normalized)
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for entry in entries:
        key = (
            entry.get("version_id") or entry.get("source_input") or "",
            entry.get("target_dir") or "",
            str(entry.get("target_name") or ""),
            str(entry.get("target_path") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


def _civitai_auth(token: str | None) -> tuple[dict[str, str], dict[str, str]]:
    headers: dict[str, str] = {}
    params: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        params["token"] = token
    return headers, params


def _civitai_status_reason(status: int, body_preview: str = "") -> str:
    body = body_preview.lower()
    if status == 401:
        return "認証失敗 (token 無効/期限切れ)"
    if status == 403:
        if "early access" in body or "supporter" in body:
            return "Early Access / supporter 限定"
        return "アクセス禁止 (地域制限または権限不足)"
    if status == 404:
        return "モデル未検出 (移行・削除・version_id誤りの可能性)"
    if status == 429:
        return "レート制限"
    if 500 <= status < 600:
        return f"サーバエラー ({status})"
    return f"HTTP {status}"


def _civitai_fetch_meta(version_id: str, token: str | None) -> tuple[dict[str, Any] | None, str]:
    headers, params = _civitai_auth(token)
    errors: list[str] = []
    for domain in CIVITAI_DOMAINS:
        url = f"https://{domain}/api/v1/model-versions/{version_id}"
        try:
            response = requests.get(url, params=params, headers=headers, timeout=CIVITAI_REQUEST_TIMEOUT)
            if response.status_code == 200:
                payload = response.json()
                payload["_resolved_domain"] = domain
                return payload, ""
            preview = (response.text or "")[:200]
            errors.append(f"{domain}: HTTP {response.status_code} - {_civitai_status_reason(response.status_code, preview)}")
            if response.status_code == 401:
                break
        except requests.RequestException as exc:
            errors.append(f"{domain}: {type(exc).__name__}: {exc}")
    return None, "\n".join(errors)


def _civitai_select_best_file(files: list[dict[str, Any]], only_safetensors: bool | None = None) -> dict[str, Any] | None:
    filtered = files
    if only_safetensors if only_safetensors is not None else CIVITAI_ONLY_SAFETENSORS:
        filtered = [entry for entry in files if (entry.get("name") or "").lower().endswith(".safetensors")]
    if not filtered:
        return None
    return sorted(filtered, key=lambda entry: (0 if entry.get("primary") else 1, -(entry.get("sizeKB") or 0)))[0]


def _civitai_build_urls(meta: dict[str, Any], chosen: dict[str, Any], version_id: str) -> list[str]:
    urls: list[str] = []
    api_url = chosen.get("downloadUrl")
    if api_url:
        urls.append(api_url)
        for src, dst in (("civitai.com", "civitai.red"), ("civitai.red", "civitai.com")):
            if f"://{src}/" in api_url:
                urls.append(api_url.replace(f"://{src}/", f"://{dst}/"))
    for domain in CIVITAI_DOMAINS:
        direct = f"https://{domain}/api/download/models/{version_id}"
        if direct not in urls:
            urls.append(direct)
    file_id = chosen.get("id")
    if file_id:
        for domain in CIVITAI_DOMAINS:
            with_file_id = f"https://{domain}/api/download/models/{version_id}?type=Model&format=SafeTensor&fileId={file_id}"
            if with_file_id not in urls:
                urls.append(with_file_id)
    return urls


def _civitai_download_requests(url: str, target: Path, token: str | None) -> tuple[bool, str]:
    headers, params = _civitai_auth(token)
    tmp = target.with_suffix(target.suffix + ".part")
    try:
        with requests.get(url, params=params, headers=headers, stream=True, timeout=CIVITAI_DL_TIMEOUT, allow_redirects=True) as response:
            if response.status_code != 200:
                preview = (response.text or "")[:200]
                return False, _civitai_status_reason(response.status_code, preview)
            with tmp.open("wb") as handle:
                for chunk in response.iter_content(1024 * 1024):
                    if chunk:
                        handle.write(chunk)
        tmp.rename(target)
        return True, ""
    except requests.RequestException as exc:
        tmp.unlink(missing_ok=True)
        return False, f"{type(exc).__name__}: {exc}"


def _civitai_download_aria2(url: str, target: Path, token: str | None) -> tuple[bool, str]:
    if not _which("aria2c"):
        return False, "aria2c not installed"
    if token and "token=" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}token={token}"
    cmd = [
        "aria2c",
        "-x",
        "16",
        "-s",
        "16",
        "-c",
        "--auto-file-renaming=false",
        "--allow-overwrite=true",
        "-d",
        str(target.parent),
        "-o",
        target.name,
        url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=CIVITAI_DL_TIMEOUT)
        if result.returncode == 0 and target.exists() and target.stat().st_size > 0:
            return True, ""
        return False, (result.stderr or result.stdout or "").strip()[-400:]
    except Exception as exc:
        return False, str(exc)


def civitai_download(entry: dict[str, Any]) -> dict[str, Any]:
    version_id = str(entry.get("version_id") or "").strip()
    record: dict[str, Any] = {
        "id": entry.get("id") or version_id or entry.get("source_input"),
        "source": "civitai",
        "kind": entry.get("kind", "lora"),
        "groups": ["civitai"],
        "source_input": entry.get("source_input"),
        "queue_origin": entry.get("queue_origin"),
        "when": datetime.now(timezone.utc).isoformat(),
        "attempts": [],
    }
    if not version_id:
        record.update(status="error: invalid version identifier", size_bytes=0, size_GiB=0.0, size_GBdec=0.0, header_ok=False)
        return record

    meta, api_error = _civitai_fetch_meta(version_id, CIVITAI_TOKEN)
    if meta is None:
        record.update(status=f"error: {api_error}", size_bytes=0, size_GiB=0.0, size_GBdec=0.0, header_ok=False)
        return record

    chosen = _civitai_select_best_file(meta.get("files") or [], entry.get("only_safetensors"))
    if chosen is None:
        record.update(status="error: no suitable file", size_bytes=0, size_GiB=0.0, size_GBdec=0.0, header_ok=False)
        return record

    target_item = {
        "target_path": entry.get("target_path"),
        "target_dir": entry.get("target_dir") or CIVITAI_DEFAULT_TARGET_DIR,
        "target_name": entry.get("target_name") or chosen.get("name") or f"civitai_{version_id}.safetensors",
    }
    target = _resolve_target(target_item)
    record["local"] = str(target)
    record["target_dir"] = str(target_item["target_dir"])
    record["target_name"] = target.name
    model_meta = meta.get("model") or {}
    record["civitai_model_name"] = model_meta.get("name")
    record["civitai_version_name"] = meta.get("name")
    if target.exists() and not CIVITAI_FORCE_REDOWNLOAD:
        size_bytes = target.stat().st_size
        record.update(
            status="exists",
            size_bytes=size_bytes,
            size_GiB=size_bytes / (1024**3),
            size_GBdec=size_bytes / 1_000_000_000,
            header_ok=validate_safetensors_header(target) if target.suffix == ".safetensors" else True,
        )
        return record

    urls = _civitai_build_urls(meta, chosen, version_id)
    for url in urls:
        method = "aria2c" if _which("aria2c") else "requests"
        ok, err = _civitai_download_aria2(url, target, CIVITAI_TOKEN) if method == "aria2c" else _civitai_download_requests(url, target, CIVITAI_TOKEN)
        if not ok and method == "aria2c":
            method = "requests (fallback)"
            ok, err = _civitai_download_requests(url, target, CIVITAI_TOKEN)
        record["attempts"].append({"url": url, "method": method, "status": "ok" if ok else "error", "error": err if not ok else ""})
        if ok:
            size_bytes = target.stat().st_size
            record.update(
                status="downloaded",
                size_bytes=size_bytes,
                size_GiB=size_bytes / (1024**3),
                size_GBdec=size_bytes / 1_000_000_000,
                header_ok=validate_safetensors_header(target) if target.suffix == ".safetensors" else True,
            )
            return record

    record.update(status="error: all candidate URLs failed", size_bytes=0, size_GiB=0.0, size_GBdec=0.0, header_ok=False)
    return record


def _manifest_path(phase: str) -> Path:
    explicit = os.environ.get("DOWNLOAD_MANIFEST_PATH")
    if explicit:
        return Path(explicit).expanduser().resolve()
    return (COMFY_BASE / "models" / f"_template_download_manifest_{phase}.jsonl").resolve()


def _write_manifest(records: list[dict[str, Any]], phase: str) -> Path:
    path = _manifest_path(phase)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def _default_manifest(name: str) -> Path:
    return (Path(__file__).resolve().parent.parent / "config" / "manifests" / name).resolve()


all_records: list[dict[str, Any]] = []

if CLI.phase in {"all", "nodes"}:
    node_manifest = _resolve_template_path(
        CLI.node_manifest or Path(os.environ.get("NODE_MANIFEST_PATH", str(_default_manifest("custom_nodes.json"))))
    )
    node_entries = _load_manifest(node_manifest, ("nodes", "items"))
    print(f"[INFO] Installing nodes from {node_manifest}")
    all_records.extend(install_nodes(node_entries))

if CLI.phase in {"all", "models"}:
    model_manifest = _resolve_template_path(
        CLI.hf_manifest or Path(os.environ.get("HF_MANIFEST_PATH", str(_default_manifest("hf_models.json"))))
    )
    model_entries = _load_manifest(model_manifest, ("models", "items"))
    print(f"[INFO] Downloading models from {model_manifest}")
    all_records.extend(download_models(model_entries))
    civitai_entries = _collect_civitai_entries()
    if civitai_entries:
        print(f"[INFO] Processing {len(civitai_entries)} CivitAI queue entries")
        for entry in civitai_entries:
            record = civitai_download(entry)
            all_records.append(record)
            print(f"[CIVITAI] {entry.get('source_input')}: {record['status']}")

manifest_path = _write_manifest(all_records, CLI.phase)
ok_count = sum(1 for record in all_records if record.get("status") in {"downloaded", "exists", "cloned", "updated"})
error_count = sum(1 for record in all_records if str(record.get("status", "")).startswith("error"))
total_size = sum(record.get("size_bytes", 0) for record in all_records)
print(f"[SUMMARY] phase={CLI.phase} ok={ok_count} error={error_count} total={total_size / 1_000_000_000:.1f}GB")
print(f"[SUMMARY] manifest={manifest_path}")
print(f"[SUMMARY] settings={SETTINGS_PATH}")
