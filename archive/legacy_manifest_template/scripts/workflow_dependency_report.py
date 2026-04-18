#!/usr/bin/env python3
"""Extract node and model dependencies from ComfyUI workflow JSON files."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


DEFAULT_WORKFLOWS = [
    Path("template_workflows/Wan2.2_I2V_SVI_Kenpechi_Workflow_v3.5 12Sec (3).json"),
    Path("template_workflows/SVI pro.json"),
    Path("template_workflows/Wan2.2_I2V_SVI_Kenpechi_Workflow_v3.5 12Sec FP8 260412.json"),
    Path("template_workflows/SVI pro FP8 260412.json"),
    Path("template_workflows/DaSiWa WAN 2.2 i2v FastFidelity C-SVI-34.json"),
]

KNOWN_REPOS = {
    "ComfyUI-WanVideoWrapper": "https://github.com/kijai/ComfyUI-WanVideoWrapper.git",
    "comfyui-wanvideowrapper": "https://github.com/kijai/ComfyUI-WanVideoWrapper.git",
    "comfyui-kjnodes": "https://github.com/kijai/ComfyUI-KJNodes.git",
    "comfyui-videohelpersuite": "https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git",
    "rgthree-comfy": "https://github.com/rgthree/rgthree-comfy.git",
    "comfyui-easy-use": "https://github.com/yolain/ComfyUI-Easy-Use.git",
    "cg-use-everywhere": "https://github.com/chrisgoringe/cg-use-everywhere.git",
    "comfyui-dream-video-batches": "https://github.com/alt-key-project/comfyui-dream-video-batches.git",
    "comfyui-mxtoolkit": "https://github.com/Smirnov75/ComfyUI-mxToolkit.git",
    "crt-nodes": "https://github.com/PGCRT/CRT-Nodes.git",
    "comfyui_essentials": "https://github.com/cubiq/ComfyUI_essentials.git",
    "comfyui-image-filters": "https://github.com/spacepxl/ComfyUI-Image-Filters.git",
    "comfyui-custom-scripts": "https://github.com/pythongosssss/ComfyUI-Custom-Scripts.git",
    "comfyui-gguf": "https://github.com/city96/ComfyUI-GGUF.git",
    "wan22fmlf": "https://github.com/wallen0322/ComfyUI-Wan22FMLF.git",
    "fblissjr/ComfyUI-WanSeamlessFlow": "https://github.com/fblissjr/ComfyUI-WanSeamlessFlow.git",
    "ComfyUI-Chibi-Nodes": "https://github.com/chibiace/ComfyUI-Chibi-Nodes.git",
}

TYPE_PREFIX_REPOS = {
    "wan": "https://github.com/kijai/ComfyUI-WanVideoWrapper.git",
    "vhs_": "https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git",
    "mx": "https://github.com/Smirnov75/ComfyUI-mxToolkit.git",
    "easy ": "https://github.com/yolain/ComfyUI-Easy-Use.git",
    "getnode": "https://github.com/yolain/ComfyUI-Easy-Use.git",
    "setnode": "https://github.com/yolain/ComfyUI-Easy-Use.git",
    "rife_": "https://github.com/Artificial-Sweetener/comfyui-WhiteRabbit.git",
    "batchresizewithlanczos": "https://github.com/Artificial-Sweetener/comfyui-WhiteRabbit.git",
    "batchwatermarksingle": "https://github.com/Artificial-Sweetener/comfyui-WhiteRabbit.git",
    "dasiwa_": "https://github.com/darksidewalker/ComfyUI-DaSiWa-Nodes.git",
    "unetloadergguf": "https://github.com/city96/ComfyUI-GGUF.git",
    "bookmark (rgthree)": "https://github.com/rgthree/rgthree-comfy.git",
    "fast groups bypasser (rgthree)": "https://github.com/rgthree/rgthree-comfy.git",
    "label (rgthree)": "https://github.com/rgthree/rgthree-comfy.git",
}

FILENAME_PATTERN = re.compile(r"[\w./\\ -]+\.(?:safetensors|gguf|onnx|pth|bin|ckpt|pt)", re.IGNORECASE)


def _iter_strings(payload: Any):
    if isinstance(payload, dict):
        for value in payload.values():
            yield from _iter_strings(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from _iter_strings(value)
    elif isinstance(payload, str):
        yield payload


def _repo_from_node(node_type: str, cnr_id: str | None, aux_id: str | None) -> str | None:
    for key in (cnr_id or "", aux_id or ""):
        if key and key in KNOWN_REPOS:
            return KNOWN_REPOS[key]
        lowered = (key or "").lower()
        if lowered in KNOWN_REPOS:
            return KNOWN_REPOS[lowered]
    lowered_type = node_type.lower()
    for prefix, repo in TYPE_PREFIX_REPOS.items():
        if lowered_type.startswith(prefix):
            return repo
    return None


def analyze_workflow(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    nodes = payload.get("nodes") or []
    node_packs: dict[str, dict[str, Any]] = {}
    node_types: dict[str, set[str]] = defaultdict(set)
    filenames: set[str] = set()
    model_urls: dict[str, set[str]] = defaultdict(set)

    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_type = node.get("type") or ""
        props = node.get("properties") or {}
        cnr_id = props.get("cnr_id")
        aux_id = props.get("aux_id")
        version = props.get("ver")
        repo_url = _repo_from_node(node_type, cnr_id, aux_id)
        pack_key = cnr_id or aux_id
        if not pack_key and repo_url:
            pack_key = repo_url.rstrip("/").split("/")[-1].removesuffix(".git")
        if not pack_key:
            pack_key = "unknown"
        entry = node_packs.setdefault(
            pack_key,
            {
                "pack_id": pack_key,
                "cnr_ids": set(),
                "aux_ids": set(),
                "versions": set(),
                "node_types": set(),
                "repo_url": repo_url,
            },
        )
        if cnr_id:
            entry["cnr_ids"].add(cnr_id)
        if aux_id:
            entry["aux_ids"].add(aux_id)
        if version:
            entry["versions"].add(str(version))
        if node_type:
            entry["node_types"].add(node_type)
            node_types[node_type].add(pack_key)

        for model_meta in props.get("models", []) or []:
            if not isinstance(model_meta, dict):
                continue
            if model_meta.get("name"):
                filenames.add(model_meta["name"])
            if model_meta.get("url"):
                model_urls[model_meta.get("name") or model_meta["url"]].add(model_meta["url"])

    for value in _iter_strings(payload):
        for match in FILENAME_PATTERN.findall(value):
            filenames.add(match.strip())

    normalized_packs = []
    for pack in node_packs.values():
        normalized_packs.append(
            {
                "pack_id": pack["pack_id"],
                "cnr_ids": sorted(pack["cnr_ids"]),
                "aux_ids": sorted(pack["aux_ids"]),
                "versions": sorted(pack["versions"]),
                "node_types": sorted(pack["node_types"]),
                "repo_url": pack["repo_url"],
            }
        )

    normalized_models = []
    for filename in sorted(filenames):
        normalized_models.append(
            {
                "filename": filename,
                "urls": sorted(model_urls.get(filename, set())),
            }
        )

    return {
        "workflow": str(path),
        "node_packs": sorted(normalized_packs, key=lambda item: item["pack_id"]),
        "model_files": normalized_models,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Workflow Dependency Report", ""]
    for workflow in report["workflows"]:
        lines.append(f"## {workflow['workflow']}")
        lines.append("")
        lines.append("### Node Packs")
        lines.append("")
        for pack in workflow["node_packs"]:
            repo = pack["repo_url"] or "(repo unresolved)"
            lines.append(f"- `{pack['pack_id']}` -> {repo}")
            if pack["node_types"]:
                lines.append(f"  types: {', '.join(pack['node_types'][:8])}")
        lines.append("")
        lines.append("### Model Files")
        lines.append("")
        for model in workflow["model_files"][:40]:
            if model["urls"]:
                lines.append(f"- `{model['filename']}` -> {model['urls'][0]}")
            else:
                lines.append(f"- `{model['filename']}`")
        lines.append("")

    lines.append("## Aggregate Node Packs")
    lines.append("")
    for pack in report["aggregate"]["node_packs"]:
        repo = pack["repo_url"] or "(repo unresolved)"
        lines.append(f"- `{pack['pack_id']}` -> {repo}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", type=Path, default=DEFAULT_WORKFLOWS)
    parser.add_argument("--json-out", type=Path, default=Path("reports/workflow_dependencies.json"))
    parser.add_argument("--md-out", type=Path, default=Path("reports/workflow_dependencies.md"))
    args = parser.parse_args()

    workflow_reports = [analyze_workflow(path) for path in args.paths]
    aggregate: dict[str, dict[str, Any]] = {}
    for workflow in workflow_reports:
        for pack in workflow["node_packs"]:
            entry = aggregate.setdefault(
                pack["pack_id"],
                {
                    "pack_id": pack["pack_id"],
                    "workflows": set(),
                    "node_types": set(),
                    "repo_url": pack["repo_url"],
                },
            )
            entry["workflows"].add(workflow["workflow"])
            entry["node_types"].update(pack["node_types"])
            if not entry["repo_url"] and pack["repo_url"]:
                entry["repo_url"] = pack["repo_url"]

    aggregate_rows = [
        {
            "pack_id": pack_id,
            "workflows": sorted(value["workflows"]),
            "node_types": sorted(value["node_types"]),
            "repo_url": value["repo_url"],
        }
        for pack_id, value in sorted(aggregate.items())
    ]

    report = {
        "workflows": workflow_reports,
        "aggregate": {
            "node_packs": aggregate_rows,
        },
    }

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.md_out.parent.mkdir(parents=True, exist_ok=True)
    args.md_out.write_text(render_markdown(report), encoding="utf-8")
    print(f"[OK] JSON report: {args.json_out}")
    print(f"[OK] Markdown report: {args.md_out}")


if __name__ == "__main__":
    main()
