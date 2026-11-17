"""R14 — engineering baseline 2.0 CI controls: zizmor, checkout credentials, grant comments,
Scorecard and the ruleset files (CI-01, CI-05, CI-06, CI-08, CI-13, DOC-04)."""

import json
import re
from pathlib import Path
from typing import Any

import yaml

from tests.helpers import REPO_ROOT

WORKFLOWS = REPO_ROOT / ".github" / "workflows"
RULESETS = REPO_ROOT / ".github" / "rulesets"
CI = WORKFLOWS / "ci.yml"
SCORECARD = WORKFLOWS / "scorecard.yml"
REVIEW = WORKFLOWS / "claude-code-review.yml"
DEPLOY = WORKFLOWS / "deploy.yml"

REQUIRED_CHECKS = {"check", "gitleaks", "semgrep", "pip-audit", "zizmor", "iac"}
# The GitHub Actions app, which reports the required checks.
GITHUB_ACTIONS_APP_ID = 15368
ID_TOKEN_JOBS = {
    (SCORECARD, "analysis"),
    (REVIEW, "claude-review"),
    (DEPLOY, "plan"),
    (DEPLOY, "apply"),
}


def load(path: Path) -> dict[Any, Any]:
    data: dict[Any, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


def workflow_paths() -> list[Path]:
    paths = sorted(WORKFLOWS.glob("*.yml"))
    assert paths
    return paths


def all_jobs() -> list[tuple[Path, str, dict[str, Any]]]:
    return [
        (path, name, job) for path in workflow_paths() for name, job in load(path)["jobs"].items()
    ]


def ruleset(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((RULESETS / name).read_text(encoding="utf-8"))
    return data


def test_r14_ci_01_zizmor_job_is_pinned_and_read_only() -> None:
    job = load(CI)["jobs"]["zizmor"]
    assert job["name"] == "zizmor"
    assert "permissions" not in job  # inherits the workflow's contents: read
    (run,) = [step["run"] for step in job["steps"] if "run" in step]
    assert re.fullmatch(
        r"uvx --exclude-newer \d{4}-\d{2}-\d{2} zizmor@\d+\.\d+\.\d+ \.github", run.strip()
    )


def test_r14_ci_06_every_checkout_sets_persist_credentials_false() -> None:
    checkouts = [
        (path.name, name, step)
        for path, name, job in all_jobs()
        for step in job["steps"]
        if step.get("uses", "").startswith("actions/checkout@")
    ]
    assert checkouts
    for path, name, step in checkouts:
        assert step.get("with", {}).get("persist-credentials") is False, (path, name)


def test_r14_ci_05_workflow_grants_are_read_only_or_empty() -> None:
    for path in workflow_paths():
        assert load(path)["permissions"] in ({"contents": "read"}, {}), path.name


def test_r14_ci_05_job_grants_each_have_a_comment() -> None:
    grants_seen = 0
    for path in workflow_paths():
        grants = re.findall(
            r"^ {6}[a-z-]+: (?:read|write|none)(?: #.*)?$",
            path.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        grants_seen += len(grants)
        for grant in grants:
            assert re.search(r" # \S", grant), (path.name, grant.strip())
    assert grants_seen


def test_r14_id_token_write_is_only_on_the_oidc_jobs() -> None:
    for path, name, job in all_jobs():
        granted = job.get("permissions", {}).get("id-token")
        if (path, name) in ID_TOKEN_JOBS:
            assert granted == "write", (path.name, name)
        else:
            assert granted is None, (path.name, name)


def test_r14_ci_13_scorecard_runs_weekly_and_on_push_to_main() -> None:
    triggers = load(SCORECARD)[True]  # PyYAML reads the bare `on` key as True
    assert set(triggers) == {"schedule", "push"}
    assert triggers["push"] == {"branches": ["main"]}
    (entry,) = triggers["schedule"]
    minute, _hour, _dom, _month, weekday = entry["cron"].split()
    assert minute.isdigit() and minute not in {"0", "00"}  # off the hour
    assert weekday.isdigit()  # weekly


def test_r14_ci_13_scorecard_publishes_and_follows_the_publishing_restrictions() -> None:
    workflow = load(SCORECARD)
    assert workflow["permissions"] == {}
    assert "env" not in workflow and "defaults" not in workflow
    (job,) = workflow["jobs"].values()
    assert "env" not in job and "defaults" not in job
    assert job["permissions"] == {
        "security-events": "write",
        "id-token": "write",
        "contents": "read",
        "actions": "read",
    }
    approved = (
        "actions/checkout@",
        "github/codeql-action/upload-sarif@",
        "ossf/scorecard-action@",
    )
    for step in job["steps"]:
        assert "run" not in step
        assert step["uses"].startswith(approved), step["uses"]
    scorecard = next(s for s in job["steps"] if s["uses"].startswith("ossf/scorecard-action@"))
    assert scorecard["with"]["publish_results"] is True
    upload = next(s for s in job["steps"] if "upload-sarif" in s["uses"])
    assert upload["with"]["sarif_file"] == scorecard["with"]["results_file"]
    ci_uploads = {
        step["uses"]
        for ci_job in load(CI)["jobs"].values()
        for step in ci_job["steps"]
        if "upload-sarif" in step.get("uses", "")
    }
    assert {upload["uses"]} == ci_uploads  # one pin for the action across the repo


def test_r14_doc_04_main_ruleset_requires_the_ci_jobs_by_name() -> None:
    main = ruleset("main.json")
    assert (main["target"], main["enforcement"], main["bypass_actors"]) == ("branch", "active", [])
    assert main["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]
    rule = next(r for r in main["rules"] if r["type"] == "required_status_checks")
    checks = rule["parameters"]["required_status_checks"]
    contexts = [check["context"] for check in checks]
    assert len(contexts) == len(set(contexts))
    assert set(contexts) == REQUIRED_CHECKS
    assert set(contexts) <= set(load(CI)["jobs"])
    assert all(check["integration_id"] == GITHUB_ACTIONS_APP_ID for check in checks)
    # A branch must be up to date with main before it merges.
    assert rule["parameters"]["strict_required_status_checks_policy"] is True


def test_r14_doc_04_main_ruleset_has_the_agreed_rules() -> None:
    rules = {r["type"]: r.get("parameters") for r in ruleset("main.json")["rules"]}
    assert set(rules) == {
        "deletion",
        "non_fast_forward",
        "required_linear_history",
        "pull_request",
        "required_status_checks",
        "code_scanning",
    }
    pull_request = rules["pull_request"]
    assert pull_request["allowed_merge_methods"] == ["squash"]
    assert pull_request["required_approving_review_count"] == 0
    assert pull_request["required_review_thread_resolution"] is True
    (tool,) = rules["code_scanning"]["code_scanning_tools"]
    assert (tool["tool"], tool["security_alerts_threshold"]) == ("CodeQL", "high_or_higher")


def test_r14_doc_04_release_tags_ruleset_blocks_delete_and_rewrite() -> None:
    tags = ruleset("release-tags.json")
    assert (tags["target"], tags["enforcement"], tags["bypass_actors"]) == ("tag", "active", [])
    assert tags["conditions"]["ref_name"]["include"] == ["refs/tags/v*"]
    assert [r["type"] for r in tags["rules"]] == ["deletion", "non_fast_forward", "update"]
