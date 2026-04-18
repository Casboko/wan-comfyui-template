#!/usr/bin/env python3
"""Summarize and sanity-check template presets."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def resolve_template_path(path: Path) -> Path:
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


def parse_settings(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith(("#", ";")) or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            values[key] = value
    return values


def split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def load_civitai_queue(path: Path) -> list[Any]:
    if not path.exists():
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
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith(("#", ";")):
                continue
            if line.startswith("{"):
                entries.append(json.loads(line))
            else:
                entries.append(line)
    return entries


def load_manifest(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Unsupported manifest shape: {path}")
    return [entry for entry in payload if isinstance(entry, dict)]


def select_by_groups(entry: dict[str, Any], include: set[str], exclude: set[str]) -> bool:
    if entry.get("enabled", True) is False:
        return False
    groups = set(entry.get("groups") or [])
    if include and not (groups & include):
        return False
    if exclude and groups & exclude:
        return False
    return True


def summarize_preset(settings_path: Path, nodes: list[dict[str, Any]], models: list[dict[str, Any]], workflow_root: Path) -> dict[str, Any]:
    settings = parse_settings(settings_path)
    node_groups = set(split_csv(settings.get("ENABLED_NODE_GROUPS")))
    model_groups = set(split_csv(settings.get("ENABLED_MODEL_GROUPS")))
    node_exclude = set(split_csv(settings.get("DISABLED_NODE_GROUPS")))
    model_exclude = set(split_csv(settings.get("DISABLED_MODEL_GROUPS")))
    workflows = split_csv(settings.get("TEMPLATE_WORKFLOW_INCLUDE"))

    selected_nodes = [entry for entry in nodes if select_by_groups(entry, node_groups, node_exclude)]
    selected_models = [entry for entry in models if select_by_groups(entry, model_groups, model_exclude)]
    model_targets = [f"{entry.get('target_dir')}/{entry.get('target_name')}" for entry in selected_models]
    model_by_dir = Counter(str(entry.get("target_dir")) for entry in selected_models)

    warnings: list[str] = []
    if settings.get("CIVITAI_TOKEN"):
        warnings.append("settings file contains CIVITAI_TOKEN")
    if any(entry.get("ref") == "main" for entry in selected_nodes):
        main_count = sum(1 for entry in selected_nodes if entry.get("ref") == "main")
        warnings.append(f"{main_count} selected custom nodes still track ref=main")
    risky_groups = [group for group in ("candidate", "lightx2v_candidate", "lightx2v_legacy", "wan21_fallback", "wan22_animate_candidate") if group in model_groups]
    if risky_groups:
        warnings.append(f"includes research/legacy model groups: {', '.join(risky_groups)}")

    missing_workflows = [name for name in workflows if not (workflow_root / name).exists()]
    if missing_workflows:
        warnings.append(f"missing workflow files: {', '.join(missing_workflows)}")

    civitai_sources = []
    civitai_entry_count = 0
    if settings.get("CIVITAI_VERSIONS"):
        env_entries = split_csv(settings["CIVITAI_VERSIONS"])
        civitai_sources.append(f"env:CIVITAI_VERSIONS ({len(env_entries)} entries)")
        civitai_entry_count += len(env_entries)
    if settings.get("CIVITAI_QUEUE_PATH"):
        queue_path = resolve_template_path(Path(settings["CIVITAI_QUEUE_PATH"]))
        if queue_path.exists():
            queue_entries = load_civitai_queue(queue_path)
            civitai_entry_count += len(queue_entries)
            civitai_sources.append(f"file:{queue_path} ({len(queue_entries)} entries)")
        else:
            civitai_sources.append(f"file:{settings['CIVITAI_QUEUE_PATH']} (missing)")
            warnings.append(f"missing CivitAI queue file: {settings['CIVITAI_QUEUE_PATH']}")

    return {
        "settings_file": str(settings_path),
        "workflow_files": workflows,
        "node_groups": sorted(node_groups),
        "model_groups": sorted(model_groups),
        "selected_nodes": [
            {"name": entry["name"], "repo": entry["repo"], "ref": entry.get("ref", "main")}
            for entry in selected_nodes
        ],
        "selected_models": [
            {
                "id": entry.get("id"),
                "source": entry.get("source", "huggingface"),
                "repo": entry.get("repo"),
                "target": f"{entry.get('target_dir')}/{entry.get('target_name')}",
                "groups": entry.get("groups", []),
            }
            for entry in selected_models
        ],
        "model_by_dir": dict(sorted(model_by_dir.items())),
        "civitai_sources": civitai_sources,
        "warnings": warnings,
        "counts": {
            "workflows": len(workflows),
            "nodes": len(selected_nodes),
            "models": len(selected_models),
            "civitai_entries": civitai_entry_count,
        },
        "model_targets": model_targets,
    }


def render_markdown(summaries: list[dict[str, Any]]) -> str:
    lines = ["# Preset Audit", ""]
    for summary in summaries:
        name = Path(summary["settings_file"]).name
        counts = summary["counts"]
        lines.append(f"## {name}")
        lines.append("")
        lines.append(f"- Workflows: {counts['workflows']}")
        lines.append(f"- Custom nodes: {counts['nodes']}")
        lines.append(f"- Models: {counts['models']}")
        lines.append(f"- CivitAI entries: {counts['civitai_entries']}")
        if summary["civitai_sources"]:
            lines.append(f"- CivitAI sources: {', '.join(summary['civitai_sources'])}")
        else:
            lines.append("- CivitAI sources: none")
        if summary["warnings"]:
            lines.append(f"- Warnings: {len(summary['warnings'])}")
            for warning in summary["warnings"]:
                lines.append(f"  - {warning}")
        else:
            lines.append("- Warnings: none")
        lines.append("")
        lines.append("### Workflows")
        lines.append("")
        for workflow in summary["workflow_files"]:
            lines.append(f"- `{workflow}`")
        lines.append("")
        lines.append("### Custom Nodes")
        lines.append("")
        for node in summary["selected_nodes"]:
            lines.append(f"- `{node['name']}` @ `{node['ref']}`")
        lines.append("")
        lines.append("### Models By Dir")
        lines.append("")
        for target_dir, count in summary["model_by_dir"].items():
            lines.append(f"- `{target_dir}`: {count}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("settings", nargs="*", type=Path, help="Settings files to audit")
    parser.add_argument("--node-manifest", type=Path, default=Path("config/manifests/custom_nodes.json"))
    parser.add_argument("--model-manifest", type=Path, default=Path("config/manifests/hf_models.json"))
    parser.add_argument("--workflow-root", type=Path, default=Path("template_workflows"))
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--md-out", type=Path)
    args = parser.parse_args()

    settings_files = args.settings or sorted(Path("config/settings").glob("*.env"))
    nodes = load_manifest(args.node_manifest)
    models = load_manifest(args.model_manifest)
    summaries = [summarize_preset(path, nodes, models, args.workflow_root) for path in settings_files]

    payload = {"presets": summaries}
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.md_out:
        args.md_out.parent.mkdir(parents=True, exist_ok=True)
        args.md_out.write_text(render_markdown(summaries), encoding="utf-8")

    for summary in summaries:
        counts = summary["counts"]
        print(
            f"[AUDIT] {Path(summary['settings_file']).name}: "
            f"workflows={counts['workflows']} nodes={counts['nodes']} models={counts['models']} "
            f"civitai={counts['civitai_entries']} warnings={len(summary['warnings'])}"
        )


if __name__ == "__main__":
    main()
