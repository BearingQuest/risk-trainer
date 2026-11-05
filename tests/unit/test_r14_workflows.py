"""R14 — CI/CD: OIDC only, plan on merge to main, apply gated by the protected prod environment."""

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.helpers import REPO_ROOT

WORKFLOWS = REPO_ROOT / ".github" / "workflows"
CI = WORKFLOWS / "ci.yml"
DEPLOY = WORKFLOWS / "deploy.yml"
SCHEDULED_AUDIT = WORKFLOWS / "scheduled-audit.yml"
REVIEW = WORKFLOWS / "claude-code-review.yml"
DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"
TERRAFORM_JOBS = ("plan", "apply")


def load(path: Path) -> dict[Any, Any]:
    data: dict[Any, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


def steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = job["steps"]
    return result


@pytest.mark.parametrize("path", sorted(WORKFLOWS.glob("*.yml")), ids=lambda p: p.name)
def test_r14_every_third_party_action_pinned_to_a_sha(path: Path) -> None:
    for uses in re.findall(r"uses:\s*([^\s#]+)", path.read_text(encoding="utf-8")):
        if uses.startswith("./"):
            continue
        assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", uses), uses


def test_r14_deploy_triggers_on_main_only() -> None:
    triggers = load(DEPLOY)[True]  # PyYAML reads the bare `on` key as True
    assert triggers["push"] == {"branches": ["main"]}
    assert set(triggers) == {"push", "workflow_dispatch"}
    assert "pull_request" not in DEPLOY.read_text(encoding="utf-8")


def test_r14_oidc_only_no_long_lived_keys() -> None:
    text = DEPLOY.read_text(encoding="utf-8")
    for forbidden in ("aws-access-key-id", "aws-secret-access-key", "AWS_ACCESS_KEY_ID"):
        assert forbidden not in text
    workflow = load(DEPLOY)
    assert workflow["permissions"] == {"contents": "read"}
    for name in TERRAFORM_JOBS:
        job = workflow["jobs"][name]
        assert job["permissions"] == {"contents": "read", "id-token": "write"}
        creds = [s for s in steps(job) if "configure-aws-credentials" in s.get("uses", "")]
        assert len(creds) == 1
        assert creds[0]["with"]["role-to-assume"].startswith("${{ vars.")


def test_r14_plan_job_has_no_environment_and_uses_the_plan_role() -> None:
    plan = load(DEPLOY)["jobs"]["plan"]
    # The plan role trusts only refs/heads/main; an environment would change the OIDC subject.
    assert "environment" not in plan
    (creds,) = [s for s in steps(plan) if "configure-aws-credentials" in s.get("uses", "")]
    assert creds["with"]["role-to-assume"] == "${{ vars.AWS_PLAN_ROLE_ARN }}"


def test_r14_apply_waits_for_the_protected_prod_environment() -> None:
    apply = load(DEPLOY)["jobs"]["apply"]
    assert apply["environment"] == "prod"
    assert apply["needs"] == "plan"
    (creds,) = [s for s in steps(apply) if "configure-aws-credentials" in s.get("uses", "")]
    assert creds["with"]["role-to-assume"] == "${{ vars.AWS_DEPLOY_ROLE_ARN }}"
    runs = " ".join(s.get("run", "") for s in steps(apply))
    assert "apply -input=false" in runs and "tfplan" in runs


def test_r14_both_jobs_build_the_package_before_terraform() -> None:
    for name in TERRAFORM_JOBS:
        job = load(DEPLOY)["jobs"][name]
        runs = [s.get("run", "") for s in steps(job)]
        package = next(i for i, r in enumerate(runs) if r == "make package")
        terraform = next(i for i, r in enumerate(runs) if "terraform" in r)
        assert package < terraform


def test_r14_deploy_has_exactly_plan_apply_smoke_and_sbom() -> None:
    assert set(load(DEPLOY)["jobs"]) == {*TERRAFORM_JOBS, "smoke", "sbom"}


def test_r14_smoke_runs_after_apply_read_only() -> None:
    smoke = load(DEPLOY)["jobs"]["smoke"]
    assert smoke["needs"] == "apply"
    assert smoke["permissions"] == {"contents": "read"}
    assert "environment" not in smoke
    assert smoke["runs-on"] == "ubuntu-24.04"
    assert smoke["timeout-minutes"] <= 15
    assert smoke["env"] == {"SMOKE_BASE_URL": "${{ vars.SMOKE_BASE_URL }}"}
    assert "secrets." not in yaml.safe_dump(smoke)
    assert not [s for s in steps(smoke) if "configure-aws-credentials" in s.get("uses", "")]
    runs = [s.get("run", "") for s in steps(smoke)]
    guard = next(i for i, r in enumerate(runs) if '-z "$SMOKE_BASE_URL"' in r)
    assert guard < runs.index("make smoke")


def test_r14_smoke_checkout_includes_static_files() -> None:
    smoke = load(DEPLOY)["jobs"]["smoke"]
    (checkout,) = [s for s in steps(smoke) if "checkout" in s.get("uses", "")]
    assert set(checkout.get("with", {})) <= {"persist-credentials"}


def locked_playwright_version() -> str:
    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    (version,) = [p["version"] for p in lock["package"] if p["name"] == "playwright"]
    return str(version)


def test_r14_e2e_runs_in_playwright_image_matching_lock() -> None:
    # The image ships the browsers for one Playwright release; a mismatch fails at launch.
    container = load(CI)["jobs"]["e2e"]["container"]
    image = re.escape(f"mcr.microsoft.com/playwright/python:v{locked_playwright_version()}-noble")
    assert re.fullmatch(image + r"@sha256:[0-9a-f]{64}", container["image"]), container["image"]
    assert container["options"] == "--user 1001"


def test_r14_e2e_installs_no_browsers_and_stays_read_only() -> None:
    workflow = load(CI)
    e2e = workflow["jobs"]["e2e"]
    assert e2e["runs-on"] == "ubuntu-24.04"
    assert e2e["timeout-minutes"] <= 10
    assert e2e.get("permissions", workflow["permissions"]) == {"contents": "read"}
    for step in steps(e2e):
        run = step.get("run", "")
        assert "playwright install" not in run and "apt-get" not in run, step.get("name")
        assert "actions/cache" not in step.get("uses", ""), step.get("uses")


def test_r14_e2e_command_matches_makefile_recipe() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    match = re.search(r"^e2e:\n((?:\t.*\n)+)", makefile, re.MULTILINE)
    assert match, "Makefile has no e2e recipe"
    recipe = "\n".join(line.removeprefix("\t") for line in match.group(1).splitlines())
    (test_step,) = [s for s in steps(load(CI)["jobs"]["e2e"]) if "pytest" in s.get("run", "")]
    assert test_step["run"].strip() == recipe


def test_r14_no_template_expressions_inside_run_scripts() -> None:
    for path in (DEPLOY, SCHEDULED_AUDIT):
        for job in load(path)["jobs"].values():
            for step in steps(job):
                assert "${{" not in step.get("run", ""), step.get("name")


def test_r14_sbom_job_publishes_the_sbom_read_only() -> None:
    workflow = load(DEPLOY)
    sbom = workflow["jobs"]["sbom"]
    assert sbom["permissions"] == {"contents": "read"}
    assert "needs" not in sbom and "environment" not in sbom
    assert sbom["runs-on"] == "ubuntu-24.04"
    assert sbom["timeout-minutes"] <= 10
    ci_uses = {s["uses"] for s in steps(load(CI)["jobs"]["pip-audit"]) if "uses" in s}
    (checkout,) = [s for s in steps(sbom) if "actions/checkout" in s.get("uses", "")]
    assert checkout["uses"] in ci_uses
    assert checkout["with"] == {"persist-credentials": False}
    runs = [s.get("run", "") for s in steps(sbom)]
    assert runs.index("uv sync --locked") < runs.index("make sbom")
    (upload,) = [s for s in steps(sbom) if "actions/upload-artifact" in s.get("uses", "")]
    assert runs.index("make sbom") < steps(sbom).index(upload)
    assert upload["with"] == {
        "name": "lambda-sbom",
        "path": "dist/sbom.cdx.json",
        "if-no-files-found": "error",
        "retention-days": 90,
    }
    others = {s["uses"] for s in steps(sbom) if "uses" in s} - {upload["uses"]}
    assert others == ci_uses, "same pinned checkout and setup-uv as CI; nothing else"
    for name in TERRAFORM_JOBS:
        assert "make sbom" not in [s.get("run", "") for s in steps(workflow["jobs"][name])]


def test_r14_scheduled_audit_runs_daily_on_main() -> None:
    workflow = load(SCHEDULED_AUDIT)
    triggers = workflow[True]  # PyYAML reads the bare `on` key as True
    assert set(triggers) == {"schedule", "workflow_dispatch"}
    (schedule,) = triggers["schedule"]
    minute, hour, *rest = schedule["cron"].split()
    assert minute.isdigit() and minute != "0", "run off the hour"
    assert hour.isdigit() and rest == ["*", "*", "*"], "once a day"
    assert workflow["concurrency"]["group"]
    (audit,) = workflow["jobs"].values()
    assert audit["if"] == "github.ref == 'refs/heads/main'"


def test_r14_scheduled_audit_is_read_only_and_bounded() -> None:
    workflow = load(SCHEDULED_AUDIT)
    assert workflow["permissions"] == {"contents": "read"}
    (audit,) = workflow["jobs"].values()
    assert "permissions" not in audit
    assert audit["runs-on"] == "ubuntu-24.04"
    assert audit["timeout-minutes"] <= 10
    (checkout,) = [s for s in steps(audit) if "actions/checkout" in s.get("uses", "")]
    assert checkout["with"] == {"persist-credentials": False}


def test_r14_scheduled_audit_matches_ci_pins_and_runs_make_audit() -> None:
    ci_uses = {s["uses"] for s in steps(load(CI)["jobs"]["pip-audit"]) if "uses" in s}
    (audit,) = load(SCHEDULED_AUDIT)["jobs"].values()
    assert {s["uses"] for s in steps(audit) if "uses" in s} == ci_uses
    assert "make audit" in [s.get("run", "") for s in steps(audit)]


def test_r14_review_workflow_skips_dependabot_and_matches_ci_checkout() -> None:
    # Dependabot runs get no Actions secrets; skip them instead of letting the bot in.
    assert "allowed_bots" not in REVIEW.read_text(encoding="utf-8")
    (review,) = load(REVIEW)["jobs"].values()
    assert review["if"] == "github.actor != 'dependabot[bot]'"
    (checkout,) = [s["uses"] for s in steps(review) if "actions/checkout" in s.get("uses", "")]
    ci_checkouts = {
        s["uses"]
        for s in steps(load(CI)["jobs"]["check"])
        if "actions/checkout" in s.get("uses", "")
    }
    assert ci_checkouts == {checkout}


def test_r14_dependabot_updates_uv_monthly_grouped_with_cooldown() -> None:
    config = load(DEPENDABOT)
    assert config["version"] == 2
    (update,) = config["updates"]
    assert update["package-ecosystem"] == "uv"
    assert update["directory"] == "/"
    assert update["schedule"]["interval"] == "monthly"
    assert update["cooldown"]["default-days"] == 7
    assert 1 <= update["open-pull-requests-limit"] <= 5
    (group,) = update["groups"].values()
    assert sorted(group["update-types"]) == ["minor", "patch"]  # majors stay separate PRs
