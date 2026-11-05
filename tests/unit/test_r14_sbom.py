"""R14 — the SBOM describes the Lambda's runtime dependencies: what ships, and nothing dev-only."""

import json
import shlex
import subprocess
from pathlib import Path
from typing import Any

from tests.helpers import REPO_ROOT

DEV_ONLY = ("pip-audit", "filelock", "moto", "pytest", "playwright")


def recipe_export_command(target: str) -> list[str]:
    """The `uv export` line from a Makefile recipe."""
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = makefile.split(f"\n{target}:\n", 1)[1].split("\n\n", 1)[0]
    line = next(line.strip() for line in recipe.splitlines() if "uv export" in line)
    return shlex.split(line)


def run_export(target: str, out: Path) -> None:
    command = recipe_export_command(target)
    command[command.index("-o") + 1] = str(out)
    subprocess.run(command, cwd=REPO_ROOT, check=True, capture_output=True)  # noqa: S603


def sbom(tmp_path: Path) -> dict[str, Any]:
    out = tmp_path / "sbom.cdx.json"
    run_export("sbom", out)
    data: dict[str, Any] = json.loads(out.read_text(encoding="utf-8"))
    return data


def component_names(data: dict[str, Any]) -> set[str]:
    return {str(c["name"]).lower() for c in data["components"]}


def test_r14_sbom_is_cyclonedx_json_of_runtime_packages(tmp_path: Path) -> None:
    data = sbom(tmp_path)
    assert data["bomFormat"] == "CycloneDX"
    assert data["specVersion"] == "1.5"
    names = component_names(data)
    assert {"fastapi", "mangum"} <= names
    for package in DEV_ONLY:
        assert package not in names, package


def test_r14_sbom_matches_what_the_package_installs(tmp_path: Path) -> None:
    requirements = tmp_path / "requirements.txt"
    run_export("package", requirements)
    installed = {
        line.split("==", 1)[0].lower()
        for line in requirements.read_text(encoding="utf-8").splitlines()
        if "==" in line and not line.startswith(" ")
    }
    assert component_names(sbom(tmp_path)) == installed
