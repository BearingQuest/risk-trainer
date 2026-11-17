"""DOC-01 — the security policy names the private reporting route, supported version and scope."""

from pathlib import Path

POLICY = (Path(__file__).parents[2] / ".github" / "SECURITY.md").read_text()


def test_doc01_points_to_private_vulnerability_reporting() -> None:
    assert "https://github.com/BearingQuest/risk-trainer/security/advisories/new" in POLICY
    assert "Security tab" in POLICY


def test_doc01_supports_only_latest_main() -> None:
    assert "latest code on `main`" in POLICY
    assert "deployed site" in POLICY


def test_doc01_scope_covers_site_answer_key_sessions_and_deploy() -> None:
    for topic in ("The live site", "The answer key", "Sessions", "The AWS deploy"):
        assert topic.lower() in POLICY.lower()
