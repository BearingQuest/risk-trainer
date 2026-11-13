"""R9 — smoke checks run against production, so they never submit a form or record an attempt."""

import ast
from pathlib import Path

import httpx
import pytest

from tests.e2e.smoke_http import read_only_client
from tests.helpers import REPO_ROOT

SMOKE_TESTS = sorted((REPO_ROOT / "tests" / "e2e").glob("test_smoke*.py"))
WRITE_CALLS = {
    "post", "put", "patch", "delete", "request", "stream", "send",
    "submit", "click", "fill", "check", "set_input_files",
}  # fmt: skip
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def violations(path: Path) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        line = f"{path.name}:{getattr(node, 'lineno', '?')}"
        if isinstance(node, ast.Import | ast.ImportFrom):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            else:
                modules = [node.module]
            for module in modules:
                if module and (module.startswith("playwright") or module == "tests.e2e.flows"):
                    found.append(f"{line} imports {module}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in WRITE_CALLS:
                found.append(f"{line} calls .{node.func.attr}()")
            if node.func.attr in {"Client", "AsyncClient"}:
                found.append(f"{line} builds its own HTTP client; use read_only_client")
        elif isinstance(node, ast.keyword) and node.arg == "method":
            found.append(f"{line} passes method=")
        elif isinstance(node, ast.Attribute) and node.attr == "event_hooks":
            found.append(f"{line} touches event_hooks")
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.strip().upper() in WRITE_METHODS
        ):
            found.append(f"{line} names HTTP method {node.value!r}")
    return found


def test_r9_smoke_tests_exist() -> None:
    assert SMOKE_TESTS


@pytest.mark.parametrize("path", SMOKE_TESTS, ids=lambda p: p.name)
def test_r9_smoke_tests_never_post(path: Path) -> None:
    assert violations(path) == []


def test_r9_violations_catches_a_form_submission(tmp_path: Path) -> None:
    sample = tmp_path / "test_smoke_bad.py"
    sample.write_text(
        "from playwright.sync_api import Page\n"
        "def test_x(client, page):\n"
        "    client.post('/s/rt-001')\n"
        "    client.request(method='POST', url='/')\n"
        "    page.get_by_role('button').click()\n",
        encoding="utf-8",
    )
    found = " ".join(violations(sample))
    expected = ("imports playwright", ".post()", ".request()", "method=", "'POST'", ".click()")
    for violation in expected:
        assert violation in found


@pytest.mark.parametrize("method", sorted(WRITE_METHODS))
def test_r9_smoke_client_refuses_writes(method: str) -> None:
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.method)
        return httpx.Response(200)

    with read_only_client("https://example.test", httpx.MockTransport(handler)) as client:
        assert client.get("/").status_code == 200
        with pytest.raises(AssertionError, match="GET only"):
            client.request(method, "/s/rt-001")
    assert sent == ["GET"]
