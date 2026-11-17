"""REPO-06: the committed pre-push hook scans only the commits being pushed with gitleaks."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests._proc import run

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / ".githooks/pre-push"
MAKEFILE = ROOT / "Makefile"

# Stands in for gitleaks: logs each call's arguments, one per line followed by
# a blank line, then exits with $FAKE_GITLEAKS_EXIT.
FAKE_GITLEAKS = """#!/bin/sh
printf '%s\\n' "$@" >> "$FAKE_GITLEAKS_LOG"
printf '\\n' >> "$FAKE_GITLEAKS_LOG"
exit "${FAKE_GITLEAKS_EXIT:-0}"
"""
# The real tools the hook and the test repos need. They are linked into one
# folder so a PATH without the fake gitleaks can't pick up a real one that
# happens to sit next to git (for example in /opt/homebrew/bin).
TOOLS = ("bash", "env", "git", "tr")


class Sandbox:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        tools = tmp_path / "tools"
        tools.mkdir()
        for name in TOOLS:
            real = shutil.which(name)
            assert real, f"{name} not found on PATH"
            (tools / name).symlink_to(real)
        fakebin = tmp_path / "fakebin"
        fakebin.mkdir()
        gitleaks = fakebin / "gitleaks"
        gitleaks.write_text(FAKE_GITLEAKS, encoding="utf-8")
        gitleaks.chmod(0o755)
        self.log = tmp_path / "gitleaks.log"
        home = tmp_path / "home"
        home.mkdir()
        self.env = {
            "PATH": f"{fakebin}{os.pathsep}{tools}",
            "HOME": str(home),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Hook Test",
            "GIT_AUTHOR_EMAIL": "hook-test@example.invalid",
            "GIT_COMMITTER_NAME": "Hook Test",
            "GIT_COMMITTER_EMAIL": "hook-test@example.invalid",
            "FAKE_GITLEAKS_LOG": str(self.log),
        }
        self.tools_only_path = str(tools)
        self.work = tmp_path / "work"
        self.git(tmp_path, "init", "-q", "-b", "main", str(self.work))

    def git(self, cwd: Path, *args: str) -> str:
        result = run(
            ["git", *args], cwd=cwd, env=self.env, capture_output=True, text=True, check=True
        )
        return str(result.stdout).strip()

    def commit(self, cwd: Path, message: str) -> str:
        self.git(cwd, "commit", "-q", "--allow-empty", "-m", message)
        return self.git(cwd, "rev-parse", "HEAD")

    def hook(self, stdin: str, **env: str) -> subprocess.CompletedProcess[str]:
        # Executed directly, so the hook's own shebang picks the shell.
        return run(
            [str(HOOK), "origin", "unused-url"],
            cwd=self.work,
            env={**self.env, **env},
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
        )

    def gitleaks_calls(self) -> list[list[str]]:
        if not self.log.exists():
            return []
        blocks = self.log.read_text(encoding="utf-8").split("\n\n")
        return [block.splitlines() for block in blocks if block]


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path)


ZERO = "0" * 40


def test_repo_06_existing_branch_scans_only_the_new_commits(sandbox: Sandbox) -> None:
    first = sandbox.commit(sandbox.work, "one")
    second = sandbox.commit(sandbox.work, "two")
    result = sandbox.hook(f"refs/heads/main {second} refs/heads/main {first}\n")
    assert result.returncode == 0, result.stderr
    assert sandbox.gitleaks_calls() == [
        ["git", "--redact", "--log-opts", f"{first}..{second}", "."]
    ]


def test_repo_06_new_branch_scans_commits_not_on_any_remote(sandbox: Sandbox) -> None:
    sandbox.commit(sandbox.work, "one")
    second = sandbox.commit(sandbox.work, "two")
    result = sandbox.hook(f"refs/heads/topic {second} refs/heads/topic {ZERO}\n")
    assert result.returncode == 0, result.stderr
    assert sandbox.gitleaks_calls() == [
        ["git", "--redact", "--log-opts", f"{second} --not --remotes", "."]
    ]


def test_repo_06_deletion_is_skipped(sandbox: Sandbox) -> None:
    first = sandbox.commit(sandbox.work, "one")
    result = sandbox.hook(f"(delete) {ZERO} refs/heads/old {first}\n")
    assert result.returncode == 0, result.stderr
    assert sandbox.gitleaks_calls() == []


def test_repo_06_push_fails_when_gitleaks_fails(sandbox: Sandbox) -> None:
    first = sandbox.commit(sandbox.work, "one")
    second = sandbox.commit(sandbox.work, "two")
    result = sandbox.hook(
        f"refs/heads/main {second} refs/heads/main {first}\n", FAKE_GITLEAKS_EXIT="1"
    )
    assert result.returncode != 0
    assert len(sandbox.gitleaks_calls()) == 1


def test_repo_06_push_fails_with_install_message_when_gitleaks_is_missing(
    sandbox: Sandbox,
) -> None:
    first = sandbox.commit(sandbox.work, "one")
    second = sandbox.commit(sandbox.work, "two")
    result = sandbox.hook(
        f"refs/heads/main {second} refs/heads/main {first}\n", PATH=sandbox.tools_only_path
    )
    assert result.returncode == 1
    assert "gitleaks not found: brew install gitleaks" in result.stderr
    assert sandbox.gitleaks_calls() == []


@pytest.mark.parametrize("gitleaks_exit", ["0", "1"])
def test_repo_06_remote_commit_missing_locally_falls_back_to_new_branch_range(
    sandbox: Sandbox, gitleaks_exit: str
) -> None:
    remote = sandbox.tmp / "remote.git"
    sandbox.git(sandbox.tmp, "init", "-q", "--bare", "-b", "main", str(remote))
    sandbox.commit(sandbox.work, "one")
    sandbox.commit(sandbox.work, "two")
    sandbox.git(sandbox.work, "remote", "add", "origin", str(remote))
    sandbox.git(sandbox.work, "push", "-q", "origin", "main")

    # A second clone rewrites the remote branch, so the remote SHA in the
    # push line is a commit the first clone has never seen.
    other = sandbox.tmp / "other"
    sandbox.git(sandbox.tmp, "clone", "-q", str(remote), str(other))
    sandbox.git(other, "commit", "-q", "--amend", "--allow-empty", "-m", "rewritten")
    sandbox.git(other, "push", "-q", "--force", "origin", "main")
    rewritten = sandbox.git(other, "rev-parse", "HEAD")

    third = sandbox.commit(sandbox.work, "three")
    missing = run(
        ["git", "cat-file", "-e", f"{rewritten}^{{commit}}"],
        cwd=sandbox.work,
        env=sandbox.env,
        capture_output=True,
        check=False,
    )
    assert missing.returncode != 0
    assert sandbox.git(sandbox.work, "rev-list", third, "--not", "--remotes") == third

    result = sandbox.hook(
        f"refs/heads/main {third} refs/heads/main {rewritten}\n",
        FAKE_GITLEAKS_EXIT=gitleaks_exit,
    )
    assert sandbox.gitleaks_calls() == [
        ["git", "--redact", "--log-opts", f"{third} --not --remotes", "."]
    ]
    if gitleaks_exit == "0":
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0


def test_repo_06_hook_is_an_executable_bash_32_script() -> None:
    text = HOOK.read_text(encoding="utf-8")
    assert os.access(HOOK, os.X_OK)
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "\nset -euo pipefail\n" in text
    # Bash 4+ only: macOS ships bash 3.2 as /bin/bash.
    for pattern in (r"\bmapfile\b", r"\breadarray\b", r"\bdeclare -A\b", r"\$\{\w+(,,|\^\^)\}"):
        assert not re.search(pattern, text), pattern


def recipe(target: str) -> list[str]:
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{target}:"))
    body = []
    for line in lines[start + 1 :]:
        if not line.startswith("\t"):
            break
        body.append(line.strip())
    return body


def test_repo_02_makefile_hooks_recipe_installs_the_committed_hooks() -> None:
    assert recipe("hooks") == ["git config core.hooksPath .githooks"]
    assert "hooks" in MAKEFILE.read_text(encoding="utf-8").splitlines()[0].split()
