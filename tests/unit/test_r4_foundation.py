"""R4 — repository foundation and CI."""

import ast
import re
from typing import Any

import pytest
import yaml

from tests.helpers import REPO_ROOT

SRC = REPO_ROOT / "src" / "risk_trainer"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def load_workflow(name: str) -> dict[Any, Any]:
    data: dict[Any, Any] = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    return data


@pytest.mark.parametrize(
    "relative",
    [
        "AGENTS.md",
        "CLAUDE.md",
        ".mcp.json",
        "README.md",
        "Makefile",
        "pyproject.toml",
        "uv.lock",
        "docs/PRD.md",
        "docs/decisions.md",
        "content/scenarios",
        "content/drafts",
        "prompts/coach_me.md",
        "src/risk_trainer/domain",
        "src/risk_trainer/content",
        "src/risk_trainer/storage",
        "src/risk_trainer/web",
        "src/risk_trainer/mcp",
        "src/risk_trainer/cli",
        "tests/unit",
        "tests/integration",
        "tests/e2e",
        ".github/workflows",
    ],
)
def test_r4_layout_matches_agents_md(relative: str) -> None:
    assert (REPO_ROOT / relative).exists(), f"missing {relative}"


FORBIDDEN_IN_DOMAIN = {"boto3", "botocore", "fastapi", "starlette", "mcp", "yaml", "typer"}
FORBIDDEN_CALLS = {"open", "eval", "exec"}


def test_r4_domain_imports_no_io_frameworks() -> None:
    problems: list[str] = []
    for path in (SRC / "domain").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                top = name.split(".")[0]
                if top in FORBIDDEN_IN_DOMAIN or top in {"os", "pathlib", "io", "shutil"}:
                    problems.append(f"{path.name}: imports {name}")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in FORBIDDEN_CALLS
            ):
                problems.append(f"{path.name}: calls {node.func.id}()")
    assert problems == []


def test_r4_workflow_actions_pinned_to_sha() -> None:
    unpinned: list[str] = []
    for path in WORKFLOWS.glob("*.y*ml"):
        for job in load_workflow(path.name)["jobs"].values():
            container = job.get("container")
            image = container.get("image") if isinstance(container, dict) else container
            if image and not re.search(r"@sha256:[0-9a-f]{64}$", image):
                unpinned.append(f"{path.name}: container {image}")
            for step in job.get("steps", []):
                uses = step.get("uses")
                if uses and not uses.startswith("./") and not re.search(r"@[0-9a-f]{40}$", uses):
                    unpinned.append(f"{path.name}: {uses}")
    assert unpinned == []


def test_r4_ci_runs_every_required_check() -> None:
    workflow = load_workflow("ci.yml")
    # PyYAML reads the bare `on` key as True.
    triggers = workflow[True]
    assert "pull_request" in triggers
    assert workflow["permissions"] == {"contents": "read"}
    jobs = workflow["jobs"]
    # The ruleset requires these names; e2e runs too but isn't required yet.
    assert set(jobs) == {"check", "gitleaks", "semgrep", "pip-audit", "zizmor", "iac", "e2e"}
    check_steps = " ".join(step.get("run", "") for step in jobs["check"]["steps"])
    for command in ("ruff check", "ruff format --check", "mypy", "pytest", "rt validate"):
        assert command in check_steps
    iac_steps = " ".join(step.get("run", "") for step in jobs["iac"]["steps"])
    for command in ("terraform fmt -check", "terraform -chdir", "validate", "checkov"):
        assert command in iac_steps


def test_r4_review_workflow_permissions_and_allowed_tools() -> None:
    text = (WORKFLOWS / "claude-code-review.yml").read_text(encoding="utf-8")
    workflow = load_workflow("claude-code-review.yml")
    assert set(workflow[True]) == {"pull_request"}
    assert "pull_request_target" not in text
    (job,) = workflow["jobs"].values()
    assert job["permissions"] == {
        "contents": "read",
        "pull-requests": "read",
        "issues": "read",
        "id-token": "write",
    }
    assert set(re.findall(r"secrets\.([A-Z0-9_]+)", text)) == {"CLAUDE_CODE_OAUTH_TOKEN"}
    action = next(s for s in job["steps"] if "claude-code-action" in s.get("uses", ""))
    # CI-14: the runner has no sandbox tooling, so the sandbox is off for this run only; the
    # reviewer has no Bash, and --allowedTools stays the inline-comment tool alone. The model is
    # pinned by exact ID (test_r14_review_workflow_pins_the_model).
    assert action["with"]["claude_args"].splitlines() == [
        "--model claude-sonnet-5-5",
        '--settings \'{"sandbox":{"enabled":false}}\'',
        '--allowedTools "mcp__github_inline_comment__create_inline_comment"',
    ]
