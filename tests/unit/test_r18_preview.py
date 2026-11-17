"""R18 — local preview: the exact "DRAFT — not published." label, and no preview when deployed."""

import shlex
from pathlib import Path

import pytest
from typer.testing import CliRunner

from risk_trainer.cli.main import PREVIEW_IN_LAMBDA, app, serve_preview
from tests._proc import run
from tests.helpers import REPO_ROOT, RT001_TEXT, WriteScenario
from tests.web_helpers import RT001_ID, client, rt001, submit

DRAFT_LABEL = "DRAFT — not published."


def test_r18_label_constant_is_exact() -> None:
    assert DRAFT_LABEL == "DRAFT — not published."
    assert "—" in DRAFT_LABEL


def test_r18_draft_banner_exact_label() -> None:
    test_client = client([rt001(status="draft")], preview=True)
    exercise = test_client.get(f"/s/{RT001_ID}").text
    assert f'<div class="banner banner-draft" role="note"><strong>{DRAFT_LABEL}</strong></div>' in (
        exercise
    )
    assert DRAFT_LABEL in submit(test_client).text


def test_r18_list_tag_exact_label() -> None:
    home = client([rt001(status="draft")], preview=True).get("/").text
    assert f'<p class="tag tag-draft">{DRAFT_LABEL}</p>' in home


EN_DASH = chr(0x2013)
EM_DASH = chr(0x2014)


@pytest.mark.parametrize(
    "variant",
    [
        "DRAFT - not published.",
        f"DRAFT {EN_DASH} not published.",
        f"DRAFT {EM_DASH} not published<",
        f"DRAFT {EM_DASH} not published</",
    ],
)
def test_r18_label_rejects_hyphen_variant(variant: str) -> None:
    test_client = client([rt001(status="draft")], preview=True)
    for page in (test_client.get("/").text, test_client.get(f"/s/{RT001_ID}").text):
        assert variant not in page


def test_r18_approved_pages_have_no_draft_label() -> None:
    test_client = client()
    for page in (test_client.get("/").text, test_client.get(f"/s/{RT001_ID}").text):
        assert DRAFT_LABEL not in page


def test_r18_preview_refused_in_lambda(
    monkeypatch: pytest.MonkeyPatch, content_dir: Path, write_scenario: WriteScenario
) -> None:
    write_scenario(RT001_TEXT)
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "risk-trainer-prod")
    import uvicorn

    def must_not_run(*args: object, **kwargs: object) -> None:
        raise AssertionError("uvicorn must not start in Lambda")

    monkeypatch.setattr(uvicorn, "run", must_not_run)
    result = CliRunner().invoke(app, ["preview", "--content-dir", str(content_dir)])
    assert result.exit_code == 1
    assert result.output == f"Refused: {PREVIEW_IN_LAMBDA}\n"
    assert "Traceback" not in result.output
    with pytest.raises(ValueError, match="local only"):
        serve_preview("127.0.0.1", 8000, content_dir, [])


def package_export_command() -> list[str]:
    """The `uv export` line from the Makefile `package` recipe: what the Lambda build installs."""
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = makefile.split("\npackage:\n", 1)[1].split("\n\n", 1)[0]
    line = next(line.strip() for line in recipe.splitlines() if "uv export" in line)
    return shlex.split(line)


def test_r18_package_excludes_uvicorn(tmp_path: Path) -> None:
    """Preview needs uvicorn, which the Lambda package doesn't install. So does `rt mcp`."""
    command = package_export_command()
    out = command.index("-o") + 1
    command[out] = str(tmp_path / "requirements.txt")
    run(command, cwd=REPO_ROOT, check=True, capture_output=True)
    packages = {
        line.split("==", 1)[0].lower()
        for line in (tmp_path / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if "==" in line and not line.startswith(" ")
    }
    assert "fastapi" in packages  # the export really ran
    assert "uvicorn" not in packages
    assert "mcp" not in packages
