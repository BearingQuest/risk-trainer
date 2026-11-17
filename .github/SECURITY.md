# Security policy

## Reporting a vulnerability

Please report security problems privately, using GitHub private vulnerability
reporting on the Security tab of this repository:

<https://github.com/BearingQuest/risk-trainer/security/advisories/new>

Please don't open a public issue or pull request for a vulnerability.

This is a personal project run by one person. I read every report, but I can't
promise a response time.

## Supported version

Only the latest code on `main` is supported, and that is what the deployed site
runs. There are no releases and no older versions to patch.

## Scope

In scope:

- The live site and what it returns to learners.
- The answer key: any way to read answer-key fields (preferred answers, expert
  rationale, debrief) before a submission, including through the public
  read-only MCP endpoint.
- Sessions: the signed session cookie, CSRF protection, the origin check that
  keeps traffic coming through CloudFront, and the submission rate limit.
- The AWS deploy: the Terraform in `infra/`, the IAM roles, and the GitHub
  Actions workflows in this repository.
- The package in `src/risk_trainer/` and the other configuration in this
  repository.

Out of scope:

- GitHub, AWS and CloudFront themselves. Report problems there to the vendor.
- Denial of service through sheer traffic volume.
