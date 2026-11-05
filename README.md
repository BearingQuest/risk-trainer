# Risk Trainer

A hosted, no-login web app that teaches security risk prioritization: five findings, limited remediation capacity, and a CISSP risk response (avoid, mitigate, transfer, accept) for each. Requirements live in [`docs/PRD.md`](docs/PRD.md). Rules for every contributor and AI agent are in [`AGENTS.md`](AGENTS.md).

## Setup

Requires [uv](https://docs.astral.sh/uv/). uv installs Python 3.14 from `.python-version`.

```sh
uv sync --locked
make check      # ruff, mypy, pytest with coverage (≥ 85% on domain + content), rt validate
make audit      # pip-audit against the locked dependencies
uv run playwright install chromium   # once, for the browser tests
make e2e        # Playwright tests of the exercise form (keyboard, 360 px, slot limit)
make package    # Lambda zip at dist/lambda.zip (arm64, Python 3.14, approved scenarios only)
make sbom       # CycloneDX SBOM of the Lambda's runtime dependencies at dist/sbom.cdx.json
```

## The `rt` CLI

| Command | What it does |
|---|---|
| `rt validate` | Validates every scenario file under `content/` and prints `file: field.path: message` for each error. Exits 1 on any error. |
| `rt approve <id> --reviewer "<name>"` | **Owner only.** Validates a draft, sets `status: approved`, `reviewed_by` and `reviewed_on` (today), and moves it from `content/drafts/` to `content/scenarios/`. |
| `rt retire <id>` | **Owner only.** Sets an approved scenario to `status: retired`. The file stays in `content/scenarios/`, and the build excludes it. |
| `rt package --out <zip> [--site-packages <dir>]` | Builds the Lambda zip: the installed dependencies plus approved scenarios only (no drafts, no retired). Writes nothing and exits 1 if any approved scenario is invalid. The zip is byte-for-byte reproducible. `make package` runs it with arm64 Python 3.14 wheels and writes `dist/lambda.zip`. |
| `rt preview [--port 8000]` | Runs the app at `http://127.0.0.1:<port>` with approved scenarios and valid drafts (labeled "DRAFT — not published."), in-memory storage and a random per-run session secret. It always binds to 127.0.0.1; there's no host option, and it refuses to run inside Lambda. |
| `rt mcp` | Runs the local authoring MCP server over stdio (PRD R16, R17) with five tools: `get_schema`, `list_scenarios`, `validate_scenario`, `score_answers`, `save_draft`. `save_draft` writes only to `content/drafts/`, always as a draft, and replaces an existing draft only with `overwrite=true`. Nothing approves content. Needs the dev dependencies (`uv sync`). |

Every command takes `--content-dir` (default `content`).

### Authoring with Claude (`rt mcp`)

Check the server in MCP Inspector once, before first use with Claude (R17):

```sh
npx -y @modelcontextprotocol/inspector@2.9.0 uv run --directory /path/to/risk-trainer rt mcp
```

To add it to Claude Code or Claude Desktop, use a stdio server entry:

```json
{
  "mcpServers": {
    "risk-trainer-authoring": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/path/to/risk-trainer", "rt", "mcp"]
    }
  }
}
```

`--directory` makes `content/` resolve inside the repo. Pass `--content-dir <path>` after `rt mcp` to use another content root. Approval stays with `rt approve`.

### Authoring a new scenario

1. **Connect `rt mcp` to Claude Code** (once). Local scope keeps the entry in your own config, out of the shared `.mcp.json`:

   ```sh
   claude mcp add --scope local risk-trainer-authoring -- uv run --directory /path/to/risk-trainer rt mcp
   ```

   Run `/mcp` in Claude Code to check that it's connected.
2. **Draft with Claude** using the five tools:
   - `get_schema`: the scenario model and the treatment and approver codes.
   - `list_scenarios`: existing IDs and coverage, so the new one doesn't clash or repeat.
   - `validate_scenario`: run it until the draft has no errors.
   - `score_answers`: check that the answer key scores the intended answers and that the slot limit forces a trade-off.
   - `save_draft`: writes `content/drafts/<id>.yaml`. Tell Claude to use `overwrite` only when you want that draft replaced.
3. **Check it in `rt preview`.** Run `uv run rt preview`, work through the draft at `http://127.0.0.1:8000` (it's labeled "DRAFT — not published."), and check it at phone width.
4. **Fact-check it.** Ask Claude to fill in [`docs/fact-check-prompt.md`](docs/fact-check-prompt.md) for the draft, and paste the result into Perplexity yourself. Triage each flagged claim: accept and reword, or reject with a reason. Revise the draft and run `validate_scenario` again.
5. **Open a save PR** with only the draft file. The PR body holds the filled fact-check prompt, the key findings with their source links, and your triage.
6. **Approve in a separate PR.** After the save PR merges, run `rt approve <id> --reviewer "<name>"` on a new branch and open a PR that lists the fact-check sources (PRD §9) and links the save PR.

Claude prepares the fact-check prompt but never calls Perplexity. Nothing approves content except `rt approve`, and only the owner runs it.

## Content layout

- `content/drafts/`: drafts only (`status: draft`, review fields null). Never deployed.
- `content/scenarios/`: approved or retired scenarios. Only approved ones are packaged.
- Each file is named `<id>.yaml`. The scenario schema is `src/risk_trainer/domain/models.py`, and the cross-field rules are in `src/risk_trainer/domain/rules.py`.

## Configuration

| Setting | Default | Notes |
|---|---|---|
| `--content-dir` (CLI option) | `content` | Content root holding `drafts/` and `scenarios/`. |
| `STORAGE_BACKEND` | **required** (no default) | `dynamodb` or `memory`. Only `rt preview` sets `memory`; the app refuses `memory` inside Lambda. |
| `SESSION_SECRET` | **required** outside Lambda | At least 32 characters; signs the session cookie. Never commit it. Refused in Lambda, which uses `SESSION_SECRET_PARAM`. |
| `SESSION_SECRET_PARAM` | none | Name of the SSM SecureString holding the session secret. Required in Lambda. |
| `ORIGIN_VERIFY_PARAM` | none | Name of the SSM SecureString holding the value CloudFront sends in `X-Origin-Verify`. Required in Lambda; requests without it get 403 (R12). |
| `ORIGIN_VERIFY_SECRET` | none | The origin header value set directly, for local testing only. Refused in Lambda. |
| `REQUESTS_PER_SESSION_PER_MINUTE` | `60` | Exercise submissions (POST) allowed per session per minute before HTTP 429 (R13). GETs aren't counted. |
| `METRICS_NAMESPACE` | `RiskTrainer` | CloudWatch namespace for the embedded-metric-format lines (`Attempts`, `RateLimited`, `RateLimitUnavailable`). |
| `DYNAMODB_TABLE` | none | Required when `STORAGE_BACKEND=dynamodb`. |
| `AWS_REGION` | boto3 default | Region of the DynamoDB table and the SSM parameters. Lambda sets it. |
| `SESSION_COOKIE_SECURE` | `true` | Sets the cookie's `Secure` flag. `rt preview` turns it off for plain-HTTP localhost. |
| `PEER_MIN_SAMPLE` | `10` | Attempts on a scenario version before the debrief shows how others answered. |
| `CONTENT_DIR` | `content` | Content root the web app loads approved scenarios from. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR`. Logs are JSON with a request ID. |

`src/risk_trainer/config.py` is the only place environment variables are read.

## Web app

| Route | What it shows |
|---|---|
| `/` | What the exercise is, and the approved scenarios (R5) |
| `/s/<id>` | The exercise form; POST scores it and returns the debrief (R6–R9) |
| `/responses`, `/about`, `/privacy` | Static pages (R10) |

POST bodies over 32 KB get 413 before parsing, and every POST needs the session's CSRF token. Submissions over `REQUESTS_PER_SESSION_PER_MINUTE` get 429 with `Retry-After: 60`. The app sends every security header itself (CSP, HSTS, nosniff, Referrer-Policy, frame-ancestors).

In AWS, the Lambda entry point is `risk_trainer.web.lambda_handler.handler` (Mangum, Function URL events). On first invocation it reads both secrets from SSM. When `ORIGIN_VERIFY_PARAM` is set, any request without the matching `X-Origin-Verify` header gets a bare 403, so only CloudFront can reach the app. The slot limit and accept fields use `static/app.js` (first party, no build step), and htmx 2.0.11 is vendored in `static/`.

Static files are served at `/static/<version>/<file>`, where the version is the first 12 hex characters of a SHA-256 over everything in `static/`. Templates build these URLs with `static_url()`. The current version is sent with `Cache-Control: public, max-age=31536000, immutable`. Any other well-formed version gets the current file with `no-store`, and unversioned paths get 404. A deploy changes the URL, so CloudFront's `/static/*` cache isn't served stale. `static/theme.js` loads in `<head>` without `defer` and sets the Auto/Light/Dark theme before first paint. The choice is kept in this browser's `localStorage` under `rt-theme`. The fonts are self-hosted under the SIL Open Font License 1.1. UI and body text use Inter, Regular and SemiBold, from the official `rsms/inter` v4.1 release, subset to Latin woff2 with fonttools. The URL, command and SHA-256 values are in `docs/decisions.md` (2026-10-29), and a unit test pins the hashes. Code and labels use IBM Plex Mono (Latin1 woff2, from the official `IBM/plex` release). The licenses are in `src/risk_trainer/web/static/fonts/OFL-Inter.txt` and `OFL-IBM-Plex-Mono.txt`. Every page starts with the Bearing Quest project-family strip. It shows `static/bearing-quest-lockup.svg`, the owner-supplied lockup, unedited and with its hash pinned by a unit test. None of this adds a configuration value.

## Infrastructure

Terraform lives in `infra/`. The owner applies `infra/bootstrap/` once (state bucket, GitHub OIDC roles); its runbook is [`infra/bootstrap/README.md`](infra/bootstrap/README.md). `infra/modules/app/` is the app (us-east-2, except the CloudFront-scope WAF web ACL in us-east-1), and `infra/envs/prod/` is the only environment (`dev/` will be added when needed).

| Resource | Notes |
|---|---|
| CloudFront distribution | HTTPS only, default `*.cloudfront.net` domain. AWS-managed policies: CachingDisabled + AllViewerExceptHostHeader for pages, CachingOptimized for `/static/*`, SecurityHeadersPolicy on both. Sends `X-Origin-Verify` from SSM. Standard logging off. |
| WAF web ACL (us-east-1) | One rate-based rule per client IP. Covered by the Free flat-rate plan after subscription. |
| Lambda + Function URL | Python 3.14, arm64, 512 MB, 10 s, reserved concurrency `lambda_reserved_concurrency`. Auth `NONE`; the app returns 403 without the CloudFront header. |
| DynamoDB table | Provisioned 25 RCU / 25 WCU (the always-free allowance for the whole Region), TTL on `expires_at`, deletion protection on. |
| IAM role | Inline policy only, capped by the bootstrap `risk-trainer-app-boundary`. |
| Logs, alarms, budgets | 14-day log group; alarms on Function URL 5xx, Lambda errors and throttles (email via SNS); a zero-spend budget and a `monthly_budget_usd` budget. |

### Terraform variables (`infra/envs/prod`)

| Variable | Default | Source / notes |
|---|---|---|
| `alert_email` | none (sensitive) | GitHub secret `ALERT_EMAIL`, as a repository secret (plan job) and a `prod` environment secret (apply job). |
| `ssm_kms_key_arn` | none | Repository variable `SSM_KMS_KEY_ARN`: `aws kms describe-key --key-id alias/aws/ssm --query KeyMetadata.Arn --output text`. |
| `lambda_zip_path` | `../../../dist/lambda.zip` | Built by `make package` in the workflow. |
| `lambda_reserved_concurrency` | `5` | `LAMBDA_RESERVED_CONCURRENCY` in the PRD (R13). Needs at least 105 unreserved concurrency in the account. |
| `requests_per_session_per_minute` | `60` | Passed to the app as `REQUESTS_PER_SESSION_PER_MINUTE`. |
| `waf_rate_limit_per_5min` | `300` | Requests per IP per 5 minutes before WAF blocks (minimum 10). |
| `monthly_budget_usd` | `1` | `MONTHLY_BUDGET_USD` in the PRD (R15). |

## Deploying

`.github/workflows/deploy.yml` runs on every push to `main` (and by hand). **plan** assumes `risk-trainer-gha-plan`, builds the package, and writes `terraform show -no-color` to the job summary after a leak check for the origin secret and alert email. **apply** waits for your approval in the `prod` environment, assumes `risk-trainer-gha-deploy`, rebuilds the (reproducible) package, re-plans and applies. **smoke** runs after a successful apply with `contents: read` only (no environment, no AWS role, no secrets) and makes GET requests to the deployed app: security headers on `/`, the HTTP→HTTPS redirect, a scenario page with five findings, and the stylesheet served `immutable` under this commit's asset version. It never submits a form, so it records no attempts (R9); a unit test fails if a smoke test sends anything but GET. The repository is public, so no plan file or JSON plan is ever uploaded.

GitHub configuration it needs:

| Name | Kind | Where |
|---|---|---|
| `TF_STATE_BUCKET`, `AWS_PLAN_ROLE_ARN`, `SSM_KMS_KEY_ARN` | variables | repository |
| `ALERT_EMAIL` | secret | repository (plan) and `prod` environment (apply) |
| `AWS_DEPLOY_ROLE_ARN` | variable | `prod` environment (required reviewer: owner; branch: `main`) |
| `SMOKE_BASE_URL` | variable | repository. The deployed `https://<distribution>.cloudfront.net` URL; no default. The smoke job fails if it's unset. Set it with `gh variable set SMOKE_BASE_URL --body "https://<distribution>.cloudfront.net"`. |

### First deploy (owner)

1. Merge, open the **plan** job summary, read the plan, approve **apply** in the `prod` environment.
2. Confirm the SNS subscription email ("AWS Notification - Subscription Confirmation").
3. Subscribe the distribution to the CloudFront Free flat-rate plan. Do it right away: until then the web ACL bills pay-as-you-go (about $0.008 an hour). The pipeline is denied this action.
   ```sh
   cd infra/envs/prod && terraform init -backend-config="bucket=<TF_STATE_BUCKET>"   # with AWS_PROFILE=rt-admin
   aws pricing-plan-manager create-subscription --profile rt-admin --region us-east-1 \
     --plan-family CloudFront --plan-tier FREE \
     --resource-arns "$(terraform output -raw distribution_arn)" "$(terraform output -raw web_acl_arn)"
   aws pricing-plan-manager list-subscriptions --profile rt-admin --region us-east-1   # FREE, ACTIVE
   ```
   Record the date in `docs/decisions.md` (it confirms R12 eligibility).
4. Run the workflow again (Actions, Deploy, Run workflow) and check that the plan shows no changes after the subscription.
5. Check it by hand:
   ```sh
   curl -sI https://<distribution>.cloudfront.net/ | grep -iE "strict-transport|content-security|x-content-type|referrer"
   curl -s -o /dev/null -w "%{http_code}\n" http://<distribution>.cloudfront.net/      # 301 to HTTPS
   curl -s -o /dev/null -w "%{http_code}\n" "$(terraform output -raw function_url)"   # 403
   make smoke SMOKE_BASE_URL=https://<distribution>.cloudfront.net        # GET only: headers, redirect, scenario page, static caching
   ```

### Rotating secrets

Both secrets are SSM SecureStrings. Run the same command used to create them, with `--overwrite`; the value is generated inline, never shown or typed:

```sh
aws ssm put-parameter --profile rt-admin --region us-east-2 --type SecureString --tier Standard --overwrite \
  --name /risk-trainer/prod/session-secret --value "$(openssl rand -base64 48)"
aws ssm put-parameter --profile rt-admin --region us-east-2 --type SecureString --tier Standard --overwrite \
  --name /risk-trainer/prod/origin-verify  --value "$(openssl rand -hex 32)"
```

Then run the Deploy workflow and approve it. Terraform reads each parameter's version into the Lambda's `SECRETS_VERSION`, so the configuration change replaces warm instances and they load the new values; for the origin secret it also updates the CloudFront header.

- Session secret: existing cookies stop validating, so an open form shows "This form has expired" once.
- Origin secret: for a few minutes while CloudFront propagates, requests can get 403. Rotate at a quiet time.

## CI

`.github/workflows/ci.yml` runs on every pull request: `check` (ruff, mypy, pytest, rt validate), `gitleaks`, `semgrep`, `pip-audit`, `iac` (terraform fmt, validate, `terraform test` with a mocked provider, and checkov), and `e2e` (Playwright, in the official Playwright image pinned by digest, whose tag must match playwright in `uv.lock`; not a required check yet). `deploy.yml` plans and applies `infra/envs/prod`, then runs read-only smoke checks against the deployed app (see Deploying). `claude-code-review.yml` runs the read-only Claude reviewer. CodeQL runs through GitHub's default setup.

## License

Risk Trainer is released under the [MIT License](LICENSE).
