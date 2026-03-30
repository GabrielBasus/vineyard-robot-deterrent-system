from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Mapping


def add_config_argument(parser: argparse.ArgumentParser) -> None:
    if any(getattr(action, "dest", "") == "config" for action in parser._actions):
        return
    parser.add_argument(
        "--config",
        type=str,
        default="",
        help="Path to a YAML parameter file. CLI flags override YAML values.",
    )


def _load_yaml_mapping(path: Path) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore
    except Exception as exc:  # pragma: no cover - import error path
        raise RuntimeError(
            "YAML config support requires PyYAML. Install it with `pip install pyyaml`."
        ) from exc

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a mapping: {path}")
    return dict(data)


def _flatten_mapping(data: Mapping[str, Any], prefix: str = "") -> Dict[str, Any]:
    flat: Dict[str, Any] = {}
    for raw_key, value in data.items():
        key = str(raw_key)
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten_mapping(value, dotted))
        else:
            flat[dotted] = value
    return flat


def _coerce_value_for_action(action: argparse.Action, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(action, argparse.BooleanOptionalAction):
        return bool(value)
    arg_type = getattr(action, "type", None)
    if arg_type is None:
        return value
    if arg_type is str:
        if isinstance(value, (list, tuple)):
            return ",".join(str(v) for v in value)
        return str(value)
    return arg_type(value)


def parse_args_with_config(
    parser: argparse.ArgumentParser,
    *,
    aliases: Mapping[str, str] | None = None,
    argv: list[str] | None = None,
) -> tuple[argparse.Namespace, Dict[str, Any]]:
    aliases = dict(aliases or {})
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--config", type=str, default="")
    pre_args, _ = pre_parser.parse_known_args(argv)

    config_path = ""
    raw_config: Dict[str, Any] = {}
    config_overrides: Dict[str, Any] = {}

    if str(pre_args.config).strip():
        config_file = Path(str(pre_args.config)).expanduser()
        raw_config = _load_yaml_mapping(config_file)
        config_path = str(config_file)

        actions_by_dest = {
            str(action.dest): action
            for action in parser._actions
            if getattr(action, "dest", None) not in (None, "help")
        }
        flat = _flatten_mapping(raw_config)
        unknown_keys: list[str] = []
        for key, value in flat.items():
            dest = key if key in actions_by_dest else aliases.get(key)
            if dest is None or dest not in actions_by_dest:
                unknown_keys.append(key)
                continue
            config_overrides[dest] = _coerce_value_for_action(actions_by_dest[dest], value)
        if unknown_keys:
            joined = ", ".join(sorted(unknown_keys))
            raise SystemExit(f"Unknown config keys in {config_file}: {joined}")
        parser.set_defaults(**config_overrides)

    args = parser.parse_args(argv)
    meta = {
        "config_path": config_path,
        "raw_config": raw_config,
        "config_overrides": config_overrides,
    }
    return args, meta


def args_to_dict(args: argparse.Namespace) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in vars(args).items():
        if isinstance(value, Path):
            out[key] = str(value)
        else:
            out[key] = value
    return out


def write_resolved_config_manifest(
    path: str | Path,
    *,
    script: str,
    args: argparse.Namespace,
    config_meta: Mapping[str, Any] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> Path:
    payload: Dict[str, Any] = {
        "script": str(script),
        "args": args_to_dict(args),
    }
    if config_meta:
        payload["config"] = dict(config_meta)
    if extra:
        payload["extra"] = dict(extra)

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path
