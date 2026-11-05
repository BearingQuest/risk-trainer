"""AGENTS.md human gates enforced by Claude Code permission rules (.claude/settings.json)."""

import json
from typing import Any

from tests.helpers import REPO_ROOT

SETTINGS = REPO_ROOT / ".claude" / "settings.json"

# Rules match command text, so they're a guardrail, not a sandbox (docs/decisions.md 2026-11-05).
REQUIRED_DENY = {
    "Bash(gh pr merge:*)",
    "Bash(terraform apply:*)",
    "Bash(terraform destroy:*)",
    "Bash(rt approve:*)",
    "Bash(rt retire:*)",
    "Bash(uv run rt approve:*)",
    "Bash(uv run rt retire:*)",
}
REQUIRED_ASK = {"Bash(git push:*)", "Bash(gh pr:*)", "Bash(gh api:*)", "Bash(python3:*)"}


def rules(kind: str) -> list[str]:
    settings: dict[str, Any] = json.loads(SETTINGS.read_text(encoding="utf-8"))
    result: list[str] = settings["permissions"][kind]
    return result


def deny_rules() -> list[str]:
    return rules("deny")


def test_bootstrap_is_not_editable_by_agents() -> None:
    # Edit rules also cover the Write tool; a Write(path) rule would never be consulted.
    assert "Edit(/infra/bootstrap/**)" in deny_rules()
    assert not any(rule.startswith("Write(") for rule in deny_rules())


def test_recursive_force_delete_is_denied() -> None:
    assert "Bash(rm -rf *)" in deny_rules()


def test_human_gates_are_denied() -> None:
    # Merging, Terraform apply/destroy and content approval stay with the owner (AGENTS.md).
    assert set(deny_rules()) >= REQUIRED_DENY


def test_outward_facing_commands_ask_first() -> None:
    assert set(rules("ask")) >= REQUIRED_ASK


def test_project_settings_grant_no_allow_rules() -> None:
    settings: dict[str, Any] = json.loads(SETTINGS.read_text(encoding="utf-8"))
    assert "allow" not in settings["permissions"]
