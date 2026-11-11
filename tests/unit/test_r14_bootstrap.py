"""R14 — bootstrap guardrails that `terraform test` can't see (lifecycle and condition operators).

The trust-policy values themselves are asserted in infra/bootstrap/tests/bootstrap.tftest.hcl.
"""

import re

import yaml

from tests.helpers import REPO_ROOT, hcl_blocks

BOOTSTRAP = REPO_ROOT / "infra" / "bootstrap"


def bootstrap_text() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(BOOTSTRAP.glob("*.tf")))


def test_r14_state_bucket_prevent_destroy() -> None:
    (bucket,) = hcl_blocks(bootstrap_text(), r'resource\s+"aws_s3_bucket"\s+"state"\s*\{')
    (lifecycle,) = hcl_blocks(bucket, r"lifecycle\s*\{")
    assert re.search(r"prevent_destroy\s*=\s*true", lifecycle)


def test_r14_oidc_audience_is_explicit() -> None:
    text = bootstrap_text()
    assert re.search(r'oidc_audience\s*=\s*"sts\.amazonaws\.com"', text)
    assert re.search(r"client_id_list\s*=\s*\[local\.oidc_audience\]", text)


def test_r14_trust_policies_use_exact_subjects() -> None:
    (role,) = hcl_blocks(bootstrap_text(), r'resource\s+"aws_iam_role"\s+"gha"\s*\{')
    assert "StringLike" not in role
    assert re.search(r'"\$\{local\.oidc_host\}:aud"\s*=\s*local\.oidc_audience', role)
    assert re.search(r'"\$\{local\.oidc_host\}:sub"\s*=\s*each\.value', role)
    text = bootstrap_text()
    # GitHub's immutable subject: owner@owner_id/name@repo_id.
    assert (
        'gh_repo    = "${local.gh_owner}@${var.github_owner_id}/'
        '${local.gh_name}@${var.github_repository_id}"' in text
    )
    assert 'plan_sub   = "repo:${local.gh_repo}:ref:refs/heads/main"' in text
    assert 'deploy_sub = "repo:${local.gh_repo}:environment:prod"' in text
    assert re.search(r'variable\s+"github_owner_id"\s*\{[^}]*default\s*=\s*"352613740"', text)
    assert re.search(r'variable\s+"github_repository_id"\s*\{[^}]*default\s*=\s*"1398551921"', text)
    assert not re.search(r'_sub\s*=\s*"[^"]*\*', text), "no wildcard in an OIDC subject"


def test_r14_no_long_lived_keys() -> None:
    text = bootstrap_text()
    for forbidden in ("aws_iam_access_key", "aws_iam_user"):
        assert forbidden not in text


def test_r14_state_bucket_cost_rules() -> None:
    text = bootstrap_text()
    assert 'sse_algorithm = "AES256"' in text, "SSE-S3, not a customer-managed KMS key"
    assert "aws_kms_key" not in text


def test_r14_iac_job_runs_terraform_test() -> None:
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    iac_steps = " ".join(step.get("run", "") for step in workflow["jobs"]["iac"]["steps"])
    assert 'terraform -chdir="$dir" test' in iac_steps
