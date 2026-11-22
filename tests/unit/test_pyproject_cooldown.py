"""uv install cooldown: exclude-newer = "7 days" is the first key under [tool.uv].

Semgrep reads a TOML table only up to the first bracket, so the key must come before any `[`,
including one in a comment. The lockfile records the span, so a loosened setting shows up there.
"""

from tests.helpers import REPO_ROOT

PYPROJECT = REPO_ROOT / "pyproject.toml"
LOCK = REPO_ROOT / "uv.lock"
COOLDOWN = 'exclude-newer = "7 days"'


def uv_table_lines_up_to_first_key() -> list[str]:
    lines = PYPROJECT.read_text(encoding="utf-8").splitlines()
    assert lines.count("[tool.uv]") == 1
    after = lines[lines.index("[tool.uv]") + 1 :]
    first_key = next(i for i, line in enumerate(after) if line.strip() and line[0] != "#")
    return after[: first_key + 1]


def test_exclude_newer_is_the_first_key_under_tool_uv_with_seven_days() -> None:
    assert uv_table_lines_up_to_first_key()[-1] == COOLDOWN


def test_no_bracket_between_the_tool_uv_header_and_exclude_newer() -> None:
    # Semgrep stops reading the table at the first bracket, so a `[` here hides the cooldown.
    between = uv_table_lines_up_to_first_key()
    assert not [line for line in between if "[" in line or "]" in line]


def test_lockfile_records_the_seven_day_span() -> None:
    assert 'exclude-newer-span = "P7D"' in LOCK.read_text(encoding="utf-8").splitlines()
