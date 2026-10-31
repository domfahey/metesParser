"""Every workspace package declares the sibling packages its source imports."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = sorted(p for p in (ROOT / "packages").iterdir() if (p / "pyproject.toml").is_file())
IMPORT = re.compile(r"^\s*(?:from|import)\s+(mp_[a-z]+)\b", re.MULTILINE)


def _declared(package: Path) -> set[str]:
    project = tomllib.loads((package / "pyproject.toml").read_text())["project"]
    requirements = list(project.get("dependencies", []))
    for extra in project.get("optional-dependencies", {}).values():
        requirements.extend(extra)
    names = {re.split(r"[<>=!~\[; ]", r, maxsplit=1)[0].strip() for r in requirements}
    return {name.replace("-", "_") for name in names if name.startswith("mp-")}


def _imported(package: Path, own: str) -> set[str]:
    found: set[str] = set()
    for source in (package / "src").rglob("*.py"):
        found.update(IMPORT.findall(source.read_text(encoding="utf-8")))
    return found - {own}


@pytest.mark.parametrize("package", PACKAGES, ids=lambda p: p.name)
def test_sibling_imports_are_declared(package: Path) -> None:
    own = package.name.replace("-", "_")
    missing = _imported(package, own) - _declared(package)
    assert not missing, f"{package.name} imports undeclared packages: {sorted(missing)}"
