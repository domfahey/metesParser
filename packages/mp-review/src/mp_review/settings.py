"""Validated, user-managed project settings; markdown is descriptive data only."""

import uuid
from pathlib import Path
from typing import Any

import yaml


class SettingsError(ValueError):
    """The local settings file is malformed or unsupported."""


class UniqueKeyLoader(yaml.SafeLoader):
    """Use safe YAML construction and reject ambiguous duplicate settings."""


def _mapping(loader: UniqueKeyLoader, node: yaml.MappingNode) -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str) or key in mapping:
            raise SettingsError("Settings keys must be unique strings.")
        mapping[key] = loader.construct_object(value_node)
    return mapping


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def read_settings(path: Path | None) -> dict[str, Any]:
    """Return defaults when absent; parse only the first fenced YAML block."""
    if path is None or not path.exists():
        return {"enabled": True}
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        if not lines or lines[0] != "---":
            raise SettingsError("Settings must start with YAML frontmatter (---).")
        end = lines.index("---", 1)
        settings = yaml.load("\n".join(lines[1:end]), Loader=UniqueKeyLoader)
        if settings is None:
            settings = {}
        if not isinstance(settings, dict):
            raise SettingsError("Settings frontmatter must be a mapping.")
        unknown = set(settings) - {"enabled", "output_dir"}
        if unknown:
            raise SettingsError(f"Unsupported settings: {', '.join(sorted(unknown))}")
        if type(settings.get("enabled", True)) is not bool:
            raise SettingsError("enabled must be a YAML boolean (true or false).")
        settings.setdefault("enabled", True)
        if "output_dir" in settings:
            value = settings["output_dir"]
            if not isinstance(value, str) or not value.strip() or Path(value).is_absolute():
                raise SettingsError("output_dir must be a non-empty project-relative path.")
            project = path.resolve().parent.parent
            target = (project / value).resolve()
            if not target.is_relative_to(project):
                raise SettingsError("output_dir must stay within the project directory.")
            settings["output_dir"] = target
        return settings
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise SettingsError(f"Invalid settings in {path}: {exc}") from exc


def output_path(settings: dict[str, Any], explicit: Path | None) -> Path:
    """Explicit CLI output wins; configured locations get a fresh child per run."""
    if explicit is not None:
        return explicit
    if "output_dir" not in settings:
        raise SettingsError("Supply --output-dir or configure output_dir in local settings.")
    return settings["output_dir"] / f"review-{uuid.uuid4().hex}"
