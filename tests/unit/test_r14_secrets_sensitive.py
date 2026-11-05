"""R14 — the repository is public: no secret or alert email can reach a log, plan summary or output.

terraform test (infra/modules/app/tests) checks the values; this checks how they are declared
and how the deploy workflow handles the plan text.
"""

import re
from typing import Any

import yaml

from tests.helpers import REPO_ROOT, hcl_blocks

MODULE = REPO_ROOT / "infra" / "modules" / "app"
PROD = REPO_ROOT / "infra" / "envs" / "prod"
DEPLOY = REPO_ROOT / ".github" / "workflows" / "deploy.yml"


def tf_text(*dirs: Any) -> str:
    return "\n".join(p.read_text(encoding="utf-8") for d in dirs for p in sorted(d.glob("*.tf")))


def test_r14_alert_email_variable_is_sensitive() -> None:
    for directory in (MODULE, PROD):
        (block,) = hcl_blocks(tf_text(directory), r'variable\s+"alert_email"\s*\{')
        assert re.search(r"sensitive\s*=\s*true", block), directory


def test_r14_origin_header_value_is_wrapped_in_sensitive() -> None:
    (header,) = hcl_blocks(tf_text(MODULE), r"custom_header\s*\{")
    assert re.search(
        r"value\s*=\s*sensitive\(data\.aws_ssm_parameter\.origin_verify\.value\)", header
    )


def test_r14_no_output_exposes_a_secret() -> None:
    for block in hcl_blocks(tf_text(MODULE, PROD), r'output\s+"\w+"\s*\{'):
        for secret in ("origin_verify", "alert_email", "session_secret", "nonsensitive"):
            assert secret not in block, block


def test_r14_session_secret_is_never_decrypted_by_terraform() -> None:
    (block,) = hcl_blocks(tf_text(MODULE), r'data\s+"aws_ssm_parameter"\s+"session_secret"\s*\{')
    assert re.search(r"with_decryption\s*=\s*false", block)


def test_r14_alert_email_comes_from_a_secret_not_a_variable() -> None:
    text = DEPLOY.read_text(encoding="utf-8")
    assert re.findall(r"ALERT_EMAIL\s*}}", text)
    assert "secrets.ALERT_EMAIL" in text
    assert "vars.ALERT_EMAIL" not in text


def test_r14_plan_is_published_only_as_redacted_text_after_a_leak_check() -> None:
    text = DEPLOY.read_text(encoding="utf-8")
    assert "-json" not in text, "JSON plans contain sensitive values in plaintext"
    plan: list[dict[str, Any]] = yaml.safe_load(text)["jobs"]["plan"]["steps"]
    names = [step.get("name", "") for step in plan]
    leak = names.index("Leak check (no secret in the plan text)")
    summary = names.index("Plan summary")
    assert leak < summary
    leak_run = plan[leak]["run"]
    assert "::add-mask::" in leak_run
    assert leak_run.index("::add-mask::") < leak_run.index("grep -qF")
    assert '"$ORIGIN" "$ALERT_EMAIL"' in leak_run
    assert "show -no-color tfplan > plan.txt" in " ".join(s.get("run", "") for s in plan)
    assert "GITHUB_STEP_SUMMARY" in plan[summary]["run"]


def test_r14_only_the_sbom_leaves_the_runner_from_a_job_without_aws_access() -> None:
    text = DEPLOY.read_text(encoding="utf-8")
    jobs: dict[str, dict[str, Any]] = yaml.safe_load(text)["jobs"]

    def uploads(job: dict[str, Any]) -> list[dict[str, Any]]:
        return [s for s in job["steps"] if "upload-artifact" in s.get("uses", "")]

    # No plan file leaves the runner: the Terraform jobs upload nothing.
    for name in ("plan", "apply"):
        assert not uploads(jobs[name]), name
    assert text.count("upload-artifact") == 1
    (job,) = [j for j in jobs.values() if uploads(j)]
    assert "id-token" not in job.get("permissions", {})
    assert not any("terraform" in s.get("run", "") + s.get("uses", "") for s in job["steps"])
    assert not any("configure-aws-credentials" in s.get("uses", "") for s in job["steps"])
    (upload,) = uploads(job)
    assert upload["with"]["path"] == "dist/sbom.cdx.json"
