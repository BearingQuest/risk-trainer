"""REPO-08: the tests start a process only through tests/_proc.py, which holds one noqa."""

import ast
import re
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
PROC = TESTS / "_proc.py"

# module -> attributes that start a process.
STARTERS = {
    "subprocess": {"run", "Popen", "call", "check_call", "check_output", "getoutput"}
    | {"getstatusoutput"},
    "os": {"system", "popen", "fork", "forkpty", "posix_spawn", "posix_spawnp"},
    "pty": {"spawn", "fork"},
    "multiprocessing": {"Process"},
}
STARTER_PREFIXES = {"os": ("spawn", "exec"), "asyncio": ("create_subprocess_",)}


def is_starter(module: str, attribute: str) -> bool:
    if attribute in STARTERS.get(module, set()):
        return True
    return attribute.startswith(STARTER_PREFIXES.get(module, ()))


def starts_a_process(node: ast.AST) -> str | None:
    """Name the process starter a node calls or imports, or None."""
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            module, attribute = func.value.id, func.attr
            if is_starter(module, attribute):
                return f"{module}.{attribute}"
    if isinstance(node, ast.ImportFrom) and node.module:
        for alias in node.names:
            if is_starter(node.module, alias.name):
                return f"from {node.module} import {alias.name}"
    return None


def other_test_files() -> list[Path]:
    return [path for path in sorted(TESTS.rglob("*.py")) if path != PROC]


def test_repo_08_the_helper_and_the_test_files_are_found() -> None:
    assert PROC.exists()
    assert other_test_files()


@pytest.mark.parametrize("path", other_test_files(), ids=lambda path: str(path.relative_to(TESTS)))
def test_repo_08_no_other_test_starts_a_process(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = [
        f"line {node.lineno}: {name}" for node in ast.walk(tree) if (name := starts_a_process(node))
    ]
    assert not found, f"{path.name} starts a process outside tests/_proc.py: {found}"


def test_repo_08_the_helper_holds_exactly_one_noqa_for_s603() -> None:
    noqa = [line for line in PROC.read_text(encoding="utf-8").splitlines() if "noqa" in line]
    assert len(noqa) == 1
    assert "noqa: S603" in noqa[0]
    assert noqa[0].split("# noqa: S603", 1)[1].strip(" #")  # the reason follows the code


def test_repo_08_no_other_test_file_ignores_s603() -> None:
    for path in other_test_files():
        text = path.read_text(encoding="utf-8")
        # This file names the rule in its own docstring and assertions.
        if path == Path(__file__):
            continue
        assert not re.search(r"noqa:[^\n]*S60\d", text), path.name


def test_repo_08_the_guard_recognises_a_starter() -> None:
    call = ast.parse("subprocess.run(['x'])").body[0]
    assert isinstance(call, ast.Expr)
    assert starts_a_process(call.value) == "subprocess.run"
    imported = ast.parse("from subprocess import run").body[0]
    assert starts_a_process(imported) == "from subprocess import run"
    tame = ast.parse("subprocess.CompletedProcess(['x'], 0)").body[0]
    assert isinstance(tame, ast.Expr)
    assert starts_a_process(tame.value) is None
