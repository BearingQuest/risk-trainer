# Risk Trainer — Product Requirements Document

| Field | Value |
|---|---|
| Working name | Risk Trainer ("Fix Two of Five") |
| Owner | Dusten Harrison, CISSP |
| Version | 1.17 — 5 Nov 2026 (supply-chain baseline, R14) |
| Status | Owner-reviewed and spec-reviewed; groups 5.1–5.4 built; v1 launched 6 Oct 2026; v1.1 complete (7 approved scenarios); group 5.6 (public stats, v1.3) in progress; read-only smoke checks run after each deploy. |
| Build path | Claude Code (plan mode) builds; a read-only Claude review agent, CodeQL and Semgrep review each pull request in GitHub Actions; the owner approves. See the Risk Trainer Build Guide. |
| Cost constraint | $0 beyond the owner's Claude subscription |

Claude Code reads this document at the start of each build group (see `AGENTS.md`). Section 5 is split into six groups (5.1–5.6). Groups 5.1–5.3 make up the v1 launch; group 5.4 follows as v1.1; group 5.5 is a stretch goal (v1.2); group 5.6, the public stats page, is v1.3. Group 5.6 doesn't depend on 5.5 and may ship before it. Anything not written here is out of scope until the owner adds it.

---

## 1. Summary

Risk Trainer is a hosted, no-login web app that teaches security risk prioritization the way a manager has to do it. The learner reads a short organizational scenario with five security findings and a fixed remediation capacity (typically two). They pick a risk treatment for each finding, write a one-line rationale and submit. They then get:

1. a deterministic score against an answer key the owner has approved,
2. the expert debrief (rationale, traps, exam tip),
3. once enough attempts exist, how other learners answered, and
4. optionally, AI coaching in their own Claude through the Risk Trainer MCP connector, grounded in that scenario's debrief (stretch goal, group 5.5).

The app itself makes no LLM calls. The owner drafts scenarios with Claude, in a chat for the launch set and through a local authoring MCP server after launch (group 5.4), and approves every one by hand.

It is the interactive companion to the owner's recorded lesson "Why We Don't Fix Everything: How Security Teams Prioritize Risk." It is aligned to CISSP Domain 1 (Security and Risk Management) concepts.

## 2. Goals and non-goals

### Goals
- G1. Teach the four risk responses (avoid, mitigate, transfer, accept) and the manager mindset: risk is likelihood × impact, and CVSS is not the same thing as risk.
- G2. Be shareable: one public URL usable in instructor applications, YouTube videos and live classes.
- G3. Stay accurate: no learner ever sees scenario content that the owner has not approved.
- G4. No AI dependency at runtime: the web exercise needs no LLM. AI coaching is optional and runs on the learner's own Claude.
- G5. Be production-grade at $0: least-privilege IAM, edge protection, hard usage ceilings with budget alerts for detection, observability and CI/CD with a human approval gate, all within AWS always-free limits and with no paid AI API.

### Non-goals (v1)
- User accounts, logins, progress tracking or certificates.
- An instructor dashboard, classes or rosters.
- Live AI-generated scenarios shown to learners.
- Any official ISC2 content, practice questions or branding.
- Mobile apps, payments or multi-language support.
- Any paid LLM API called by the app (Bedrock or others). That's a v2 option only if a budget ever exists.

## 3. Users and primary use cases

| User | Use case |
|---|---|
| New security analyst | Works foundational scenarios, which use workplace framing and end with an on-the-job tip |
| CISSP candidate | Works intermediate and advanced scenarios, which use CISSP Domain 1 terms and end with an exam tip |
| Owner as instructor | Uses a scenario live in a class or on a recording, then shows the peer distribution |
| Hiring manager / reviewer | Opens the link from an application and completes one scenario in under 10 minutes |
| Owner as author | Drafts scenarios with Claude through the authoring MCP server, fact-checks and edits them, then approves them for publication |
| Learner using Claude (stretch) | Adds the Risk Trainer connector to Claude and works scenarios in chat, coached by their own Claude |

## 4. Core concepts

### 4.1 Risk treatments
The treatment set uses CISSP exam terminology, with the owner's lesson vocabulary shown as aliases:

| Code | UI label | Meaning |
|---|---|---|
| `avoid` | Avoid — stop the activity | Eliminate the risk by discontinuing the activity or asset that creates it |
| `mitigate_remediate` | Mitigate: remediate ("fix") | Remove the vulnerability (patch, reconfigure, replace). **Consumes one remediation slot.** |
| `mitigate_compensate` | Mitigate: compensating control ("reduce") | Lower likelihood or impact without removing the vulnerability (segment, restrict, monitor) |
| `transfer` | Transfer / share | Shift financial impact to a third party (insurance, contract). Accountability stays with the organization. |
| `accept` | Accept | A documented, informed decision to retain the risk. **Requires choosing who approves the acceptance.** |

Ignoring or rejecting a risk is not an option. The debrief says so wherever it is relevant.

### 4.2 Acceptance approvers
When a learner picks `accept`, they must choose an approver:

| Code | UI label |
|---|---|
| `security_team` | Security team |
| `it_operations` | IT operations (runs the system) |
| `business_risk_owner` | Business owner of the affected asset or process |
| `senior_management` | Executive leadership / risk committee |

Each scenario's answer key lists the correct and acceptable approvers. The teaching point: the security team advises on risk but does not accept it, and whoever runs a system doesn't necessarily own its risk.

### 4.3 Remediation capacity
Every scenario sets `context.capacity.remediation_slots` (default 2). No more than that many findings can be assigned `mitigate_remediate`. Both the UI and the server enforce this.

### 4.4 Scenario lifecycle
`draft` → (owner review) → `approved` → optionally `retired`. Only `approved` scenarios are packaged into a deployment. Drafts are visible only in the local preview.

## 5. Functional requirements

Acceptance criteria use EARS-style phrasing. "The system" means the deployed web app unless the text says the CLI.

### 5.1 Group: `content-foundation`

**R1 — Scenario schema.** As the author, I want a strict schema so that invalid content cannot ship.
- The system SHALL define scenarios as YAML files validated by a Pydantic v2 model covering the fields in Appendix A.
- The system SHALL require exactly one answer-key entry for every finding, and no key entries without a finding.
- The system SHALL require each finding's `preferred` treatment to also appear in its `acceptable` list.
- The `preferred` treatments across a scenario's findings SHALL cover at least three of the four responses (avoid, mitigate, transfer, accept); both mitigate codes count as mitigate.
- IF `difficulty` is `foundational`, THEN `job_tip` SHALL be present. IF `difficulty` is `intermediate` or `advanced`, THEN `exam_tip` SHALL be present. Either scenario MAY include both.
- IF the answer key's `preferred` treatments assign `mitigate_remediate` to more findings than `remediation_slots`, THEN validation SHALL fail.
- IF a finding's `preferred` or `acceptable` treatments include `accept`, THEN its key SHALL define `approvers.correct` with at least one value.
- IF `status` is `approved`, THEN `reviewed_by` and `reviewed_on` SHALL be present.
- Finding IDs SHALL be unique within a scenario, and scenario IDs SHALL be unique across the repository.
- Scenario IDs SHALL match `^rt-[0-9]{3}-[a-z0-9]+(-[a-z0-9]+)*$` and be at most 64 characters. Finding IDs SHALL be `F1` to `F5`.
- `security_team` SHALL NOT appear in any finding's `approvers.correct` or `approvers.acceptable`: security advises on risk but never accepts it.
- `context.organization` SHALL end with "(fictional)".
- IF neither a finding's `preferred` nor its `acceptable` treatments include `accept`, THEN its key SHALL NOT define `approvers`. No approver SHALL appear in both `approvers.correct` and `approvers.acceptable`.
- Each `expert_rationale` SHALL be at most 120 words; each finding's `key_considerations` SHALL have 2–4 items; `cvss_base` SHALL be null or 0.0–10.0; `cissp_domains` SHALL be unique values from 1 to 8.
- No text field SHALL contain a CVE identifier (`CVE-YYYY-NNNN…`).
- Unknown fields, duplicate YAML keys and type coercion (for example `"1"` for an integer) SHALL fail validation.

**R2 — Validation CLI.** As the author, I want one command that tells me exactly what is wrong.
- WHEN the author runs `rt validate`, THEN the CLI SHALL validate every file under `content/` and print file, field path and message for each error.
- WHEN validation fails, THEN the CLI SHALL exit non-zero.
- Each scenario file SHALL be named `<id>.yaml`. Files in `content/drafts/` SHALL have `status: draft` with `reviewed_by` and `reviewed_on` null; files in `content/scenarios/` SHALL be `approved` or `retired`, with `reviewed_by` and `reviewed_on` set. Symlinks and files outside those two folders SHALL fail validation.

**R3 — Approval workflow.** As the author, I want approval to be an explicit human act.
- WHEN the author runs `rt approve <scenario-id> --reviewer "<name>"`, THEN the CLI SHALL validate the scenario, set `status: approved`, `reviewed_by` and `reviewed_on` (today, ISO date), and move the file from `content/drafts/` to `content/scenarios/`.
- IF validation fails, THEN the CLI SHALL refuse to approve and leave the file unchanged.
- WHEN the author runs `rt retire <scenario-id>`, THEN the CLI SHALL set `status: retired`, and the build SHALL exclude it. Only an approved scenario can be retired; the file stays in `content/scenarios/` and keeps `reviewed_by` and `reviewed_on`.
- `rt approve` and `rt retire` SHALL change only the top-level `status`, `reviewed_by` and `reviewed_on` lines (comments and formatting elsewhere are preserved), SHALL re-validate the result before writing, and SHALL write atomically (a temporary file in the same folder, then a rename). `rt approve` SHALL refuse if the target file already exists.

**R4 — Repository foundation and CI.**
- The repository SHALL have the layout defined in `AGENTS.md`.
- WHEN a pull request is opened or updated, THEN CI SHALL run lint (ruff), type check (mypy), tests (pytest), `rt validate`, secret scanning (gitleaks), static analysis (Semgrep), dependency audit (pip-audit), and `terraform fmt -check` / `validate` plus an IaC security scan (checkov) once `infra/` exists. A separate Claude review agent and GitHub CodeQL review the same pull request.
- The review workflow SHALL trigger on `pull_request` only (never `pull_request_target`), pin every action to a commit SHA, and grant the job only `contents: read`, `pull-requests: read`, `issues: read` and `id-token: write` (claude-code-action needs it to obtain its GitHub App token). Its only secret SHALL be `CLAUDE_CODE_OAUTH_TOKEN`, and its only allowed tool SHALL be the inline-comment tool. That tool list, not the token, is what keeps the reviewer from pushing.
- IF any check fails, THEN the pull request SHALL be blocked from merging.

### 5.2 Group: `exercise-flow`

**R5 — Home and scenario list.**
- The home page SHALL explain the exercise in no more than 120 words and link to a reference page describing the four treatments.
- The scenario list SHALL show each approved scenario's title, difficulty, estimated minutes and CISSP domain tags.
- WHEN the author runs `rt preview`, THEN the CLI SHALL serve the app on 127.0.0.1 only (there is no option to change the host, and any non-loopback address SHALL be refused), with approved scenarios and valid drafts, in-memory storage, and a DRAFT banner on every draft scenario's pages. The deployed app SHALL never show drafts.

**R6 — Exercise page.**
- WHEN a learner opens a scenario, THEN the system SHALL show the organizational context, the remediation capacity and all five findings with their signals.
- The system SHALL require one treatment per finding.
- WHEN a learner chooses `accept` for a finding, THEN the system SHALL require a rationale for that finding (10–600 characters). For any other treatment the rationale is optional (0–600 characters). An overall note (0–1,200 characters) is optional.
- WHEN a learner selects `accept`, THEN the system SHALL require an approver selection for that finding.
- WHILE the number of findings set to `mitigate_remediate` equals `remediation_slots`, the system SHALL disable further remediate selections and say why.
- The form SHALL be fully usable by keyboard and at 360 px viewport width.

**R7 — Submission and scoring.**
- WHEN a learner submits, THEN the server SHALL re-validate every constraint in R6 and reject violations with HTTP 422 and a message the learner can understand.
- The server SHALL accept a submission only if it has exactly one answer for each of the scenario's finding IDs, with no duplicate or unknown IDs.
- The server SHALL reject request bodies larger than 32 KB with HTTP 413 before parsing them.
- Every POST SHALL carry the session's CSRF token; a missing or wrong token SHALL get HTTP 403.
- An approver sent for a treatment other than `accept` SHALL be ignored and not recorded. Rationale and note lengths SHALL be counted after trimming whitespace.
- The system SHALL score each finding deterministically per Section 7 and show the total as points and as a percentage.
- The score SHALL NOT depend on the rationale text or on any AI output.

**R8 — Debrief.**
- WHEN scoring completes, THEN the system SHALL show a per-finding table (learner's choice, expert choice, points), the expert rationale, key considerations, common traps, and the scenario's job tip and/or exam tip from the answer key.
- WHERE a learner chose `accept` with an approver that is not correct, the debrief SHALL state who should approve and why. The "why" SHALL be fixed text per approver role, phrased as what is typical under the organization's governance rather than as an absolute rule, with a separate message when `senior_management` is acceptable but not correct.
- WHERE the answer key has a `why_not` entry for the learner's treatment on a finding (and that treatment is not preferred), the debrief SHALL show it for that finding.
- The debrief SHALL show the learner's own rationale and overall note in that response only. They SHALL NOT be stored or logged.
- Responses to a submission (POST) SHALL send `Cache-Control: no-store`.

**R9 — Peer distribution.**
- WHEN a submission is scored, THEN the system SHALL record the structured choices (scenario ID and version, per-finding treatment and approver, score, timestamp). It SHALL NOT record rationale text, overall notes, IP address or user agent.
- WHILE a scenario version has at least `PEER_MIN_SAMPLE` (default 10) recorded attempts, the debrief SHALL show the percentage of learners choosing each treatment for each finding.
- Raw attempt records SHALL carry a DynamoDB TTL of the submission time plus 180 days, and every read SHALL exclude records past that time (DynamoDB deletes expired items later, on its own schedule). Aggregate counters SHALL persist.
- The learner's own attempt SHALL be recorded before the debrief renders and SHALL count toward `PEER_MIN_SAMPLE`. A resubmitted form (same submission ID) SHALL NOT be counted twice.
- IF storage fails, THEN the learner SHALL still get the score and debrief, without peer results.
- `STORAGE_BACKEND` (`memory` or `dynamodb`) SHALL have no default outside `rt preview`, and the app SHALL refuse to start with `memory` inside Lambda (`AWS_LAMBDA_FUNCTION_NAME` set).

**R10 — Static pages.** The system SHALL include About, Privacy and "The four responses" reference pages. About SHALL state that scenarios are AI-drafted, fact-checked and human-approved, and that the site is not affiliated with or endorsed by ISC2. Until R19 ships, About SHALL NOT mention the MCP connector. Privacy SHALL state that the site sets one session cookie, used only to protect form submissions, with no tracking. Privacy SHALL also describe the stats page and its monthly totals (R22).

### 5.3 Group: `aws-deployment`

**R11 — Infrastructure as code.** All AWS resources SHALL be defined in Terraform under `infra/`, with remote state in S3 using native state locking (`use_lockfile = true`) and no DynamoDB lock table. S3 is not always-free: the state bucket SHALL hold only Terraform state (expected under 1 MB), whose storage and request cost rounds to $0.00 a month.

**R12 — Edge and security.**
- The system SHALL be served only over HTTPS through CloudFront.
- WHERE the AWS account is eligible, the distribution SHALL be subscribed to CloudFront's Free flat-rate plan and SHALL use its included WAF, with a rate-based rule per client IP.
- IF the account is not eligible, THEN the system SHALL NOT add a paid standalone WAF; it SHALL rely on application rate limits (R13) and Lambda reserved concurrency.
- Eligibility for the Free flat-rate plan is confirmed when the owner subscribes the distribution to the Free plan, and the owner records the date in `docs/decisions.md`.
- The application SHALL send HSTS, a strict Content-Security-Policy (no inline scripts, no third-party script origins), X-Content-Type-Options, Referrer-Policy and frame-ancestors 'none' on every response. CloudFront SHALL attach the AWS-managed SecurityHeadersPolicy as a backstop. (The Free flat-rate plan allows only AWS-managed response-headers policies, and the managed policy keeps the origin's values.)
- Fonts SHALL be self-hosted; pages SHALL load no third-party font or script origins. Static assets SHALL be served under a content-versioned path with a long-lived immutable cache header, so a deploy isn't served stale from the edge cache.
- The application origin (a Lambda Function URL) SHALL reject with HTTP 403 every request that does not carry the secret origin header CloudFront adds, before reading the session or the body. The header value SHALL be an SSM SecureString, and the app SHALL refuse to start in Lambda without it.

**R13 — Compute, data and cost ceilings.**
- The app SHALL run on AWS Lambda (Python) behind CloudFront, with reserved concurrency set by `LAMBDA_RESERVED_CONCURRENCY` (default 5).
- Session and attempt data SHALL live in DynamoDB in provisioned-capacity mode with TTL enabled. Provisioned capacity across all tables SHALL total no more than 25 RCU and 25 WCU, with auto scaling off, and stored data SHALL stay under 1 GB (the always-free allowance is 25 RCU, 25 WCU and 25 GB).
- The application SHALL limit each session to `REQUESTS_PER_SESSION_PER_MINUTE` (default 60) exercise submissions (POST) per minute and return HTTP 429 above it. GET requests are not counted. The count is kept in DynamoDB with a TTL. IF the counter is unavailable, THEN the submission SHALL proceed, and the event SHALL be logged and counted as a metric. A new session resets this limit, so it is a courtesy limit, not an abuse control; the abuse backstops are the WAF per-IP rate rule (where eligible) and Lambda reserved concurrency.
- Secrets SHALL live in SSM Parameter Store SecureString (standard tier) and SHALL NOT be in the repository or in Lambda environment variables in plaintext. The app SHALL refuse to start in Lambda if a plaintext secret is set in its environment.
- CloudWatch log groups SHALL keep logs for 14 days.

**R14 — CI/CD.**
- Deployments SHALL use GitHub Actions with OIDC federation to AWS; no long-lived AWS keys.
- WHEN a change merges to `main`, THEN CI SHALL produce a Terraform plan, and apply SHALL wait for manual approval through a protected GitHub environment.
- WHEN apply succeeds, THEN CI SHALL run read-only smoke checks (GET only) against the deployed URL, with no AWS credentials or secrets: security headers, a scenario page with five findings, `/stats` returning 200 (whatever the counts), and the stylesheet served `immutable` under the commit's static asset version. They SHALL NOT submit a form or record an attempt.
- The build SHALL package only `approved` scenarios (`rt package`). IF any approved scenario fails validation, THEN the build SHALL fail and write no package. The same inputs SHALL produce a byte-identical package. Changes to `README.md` or files under `docs/` SHALL NOT change the package. The package SHALL include the repository's `LICENSE` file in the app's dist-info, so a change to `LICENSE` changes the package.
- A scheduled workflow SHALL run the dependency audit (`make audit`) daily on `main`. Each deploy run SHALL publish, from a job with no AWS credentials, a CycloneDX SBOM of the Lambda's runtime dependencies as a build artifact, outside the package. The build backend SHALL be pinned to an exact version.

**R15 — Observability and cost.**
- Logs SHALL be structured JSON with a request ID. Rationale text SHALL never be logged.
- The system SHALL emit metrics for attempts, 429 responses, rate-limit counter failures and, once group 5.5 ships, MCP tool calls, as CloudWatch embedded metric format log lines with no dimensions. Custom metrics SHALL stay within the always-free allowance (10).
- Alarms SHALL notify the owner by email (SNS) on sustained 5xx errors, Lambda errors and Lambda throttles.
- AWS Budgets SHALL alert by email on any spend beyond the Free Tier (Zero spend budget) and above `MONTHLY_BUDGET_USD` (default 1). Budgets detect spend, can lag by hours, and cap nothing. Spending is capped by Lambda reserved concurrency, DynamoDB provisioned capacity (it throttles instead of billing more), the CloudFront flat-rate plan's no-overage terms, and the rate limits in R13.

### 5.4 Group: `authoring-mcp` (v1.1, after launch)

**R16 — Authoring MCP server.** As the author, I want Claude to draft and check scenarios through tools I control.
- WHEN the author runs `rt mcp`, THEN the CLI SHALL start a local MCP server over stdio, built with the official MCP Python SDK.
- The server SHALL expose exactly these tools: `get_schema`, `list_scenarios`, `validate_scenario`, `score_answers`, `save_draft` (contracts in Section 8.1).
- The server SHALL NOT expose any tool that approves, retires or deletes a scenario, or that edits `status`, `reviewed_by` or `reviewed_on`.
- Every tool SHALL validate its input and return a structured error, never a stack trace.

**R17 — Draft safety.**
- WHEN `save_draft` is called, THEN the server SHALL validate the scenario (R1) and write it only if validation passes.
- The server SHALL write only under `content/drafts/`, SHALL reject any path that resolves outside it, and SHALL force `status: draft`, `reviewed_by: null` and `reviewed_on: null`.
- The server SHALL build the file name only from the validated scenario ID (R1 pattern), SHALL refuse to write through or onto a symlink, and SHALL write atomically (a temporary file in the same directory, then a rename).
- IF a scenario ID already exists in `content/scenarios/`, THEN `save_draft` SHALL refuse and name the conflict, whatever `overwrite` says.
- IF a draft with the same ID already exists in `content/drafts/`, THEN `save_draft` SHALL refuse unless `overwrite` is true. The tool description SHALL tell the assistant to set `overwrite` only when the owner asks for that draft to be replaced, and the result SHALL say when an existing draft was replaced (`replaced: true`).
- Tests SHALL call every tool in-process, and the owner SHALL verify the server in MCP Inspector before first use with Claude.

**R18 — Local preview.**
- WHEN the author runs `rt preview`, THEN the CLI SHALL start the app locally with drafts visible and clearly labeled "DRAFT — not published."
- Preview mode SHALL NOT be available in the deployed environment.

### 5.5 Group: `learner-mcp` (stretch, v1.2)

**R19 — Public learner MCP endpoint.**
- The deployed app SHALL serve an MCP endpoint at `/mcp` using stateless streamable HTTP with JSON responses, from the same Lambda as the web app.
- The endpoint SHALL expose the tools `list_scenarios`, `get_scenario` and `submit_answers`, and the prompt `coach_me` (contracts in Section 8.2).
- The endpoint SHALL require no login and SHALL be read-only: it records no attempts and updates no aggregates.
- The endpoint SHALL NOT use cookies or browser CSRF tokens. It SHALL validate the Host header against the deployed hostname, reject any request whose Origin header is present and not on an explicit allow-list, and send no permissive CORS headers. Tests SHALL cover these checks both directly and through CloudFront.
- The endpoint SHALL enforce an endpoint-wide request cap (`MCP_REQUESTS_PER_MINUTE`, default 60) rather than a per-IP limit, because connector traffic arrives from the AI provider's servers.
- WHEN the endpoint ships, THEN the About page SHALL state that any coaching through the MCP connector is generated by the learner's own AI assistant, not by the site (moved from R10).

**R20 — Learner MCP safety.**
- `get_scenario` SHALL NEVER return answer-key content. Only `submit_answers` returns it, after scoring.
- Only approved scenarios SHALL be reachable. Inputs SHALL be validated with the same rules as R7, including exactly one answer per finding and the 32 KB body limit.
- `submit_answers` SHALL score and return the debrief but SHALL NOT record an attempt, so peer statistics come only from the web exercise.
- Tool and prompt descriptions SHALL be static strings in code, never built from stored content.
- Rationale text submitted through MCP SHALL NOT be stored or logged (same as R9).

**R21 — Connector compatibility.**
- Before building R19–R20 in full, a one-tool spike SHALL confirm that Claude accepts the deployed endpoint as a custom connector with no authentication.
- WHEN a learner adds the endpoint as a Claude custom connector, THEN they SHALL be able to list scenarios, fetch one, submit answers and receive the debrief in chat.

### 5.6 Group: `public-stats` (v1.3)

**R22 — Public stats page.**
- WHEN a web submission records a new attempt (R9), THEN the system SHALL add it to a monthly stats bucket for that scenario version (UTC calendar month) with one atomic UpdateItem ADD: the attempt count, the count for each finding's treatment, the approver for each accept answer, and the total score. The bucket SHALL carry a TTL at the start of the seventh month after its month. A resubmitted form SHALL NOT be added twice. IF the bucket update fails, THEN the attempt SHALL stay recorded, the learner SHALL still get the debrief, and the failure SHALL be logged. The peer aggregates (R9) SHALL be unchanged.
- The system SHALL serve `GET /stats`, a server-rendered page that needs no JavaScript. Other methods SHALL be refused (405). It SHALL add no write path.
- The page SHALL total the buckets over a rolling window of the current month and the five before it, starting no earlier than the first deploy month (`STATS_FIRST_MONTH`), with no backfill. It SHALL say "since <month>" and count only the current version of each approved scenario.
- It SHALL show site-wide attempts and attempts by difficulty. Per scenario, it SHALL show attempts, the median score, score bands, and per finding the share choosing the preferred answer and the most common other choice. On findings where accept is preferred, it SHALL show the share of learners who chose accept and named the security team or IT operations as the approver (the trap rate).
- Privacy: totals only. A scenario SHALL show no figures until its window total reaches `PEER_MIN_SAMPLE` (the same setting as R9); single months are not checked on their own. Site-wide and per-difficulty totals SHALL count only scenarios at or above it. The trap rate SHALL show only when at least `PEER_MIN_SAMPLE` learners chose accept on that finding. Percentages SHALL be whole numbers. The page SHALL NOT show submission or session IDs, dates or times finer than the month, per-attempt rows or free text.
- The page SHALL state in plain words that learners are self-selected, the totals include the owner's own test attempts, the window rolls over about six months, and it is a learning tool, not research.
- Each instance SHALL cache the totals for 5 minutes. IF the totals can't be read, THEN the page SHALL return 503 with a plain message, and the failure SHALL be cached for 30 seconds.
- The main navigation SHALL link to the page, and the Privacy page SHALL describe the monthly totals, their retention, what the stats page shows and the minimum sample.

## 6. Non-functional requirements

| Area | Requirement |
|---|---|
| Security | OWASP ASVS Level 1 baseline. Signed session cookie (HttpOnly, Secure, SameSite=Lax); CSRF token on every state-changing request; server-side input length limits; Jinja autoescape on; htmx vendored and served from the app's own origin. MCP servers follow the least-privilege tool sets in R16 and R19. |
| Privacy | No accounts and no direct identifiers (name, email, IP address, user agent) in application data. The app keeps a pseudonymous session ID in a signed cookie and records structured choices with a timestamp per attempt (R9). A per-session submission counter, keyed by that random session ID, expires after 2 minutes (R13). Monthly stats totals, not linked to any attempt, expire about 7 months after their month (R22). Free text is not persisted or logged, whether it arrives through the web or MCP. Outside the app: CloudWatch Logs (14 days; request IDs, no IP addresses logged by the app), CloudFront standard logging off, AWS WAF sampled requests (include IP addresses; AWS keeps them for up to 3 hours), and GitHub Actions logs (no learner data). The Privacy page lists each of these with its retention. |
| Reliability | No runtime dependency on any LLM. The web exercise works whether or not the MCP endpoint exists. |
| Performance | p95 server time under 500 ms for web routes at demo load (warm). Cold starts of up to about 5 s are acceptable for v1. |
| Cost | $0 target: AWS always-free limits, CloudFront Free flat-rate plan where eligible, no paid APIs, no custom domain in v1. The hard ceilings in R13 and R15 cap spend; budget alerts only detect drift. |
| Accessibility | WCAG 2.2 AA target: labels on all inputs, visible focus, color never the only signal, usable at 360 px. Text contrast at least 4.5:1, and UI component and focus contrast at least 3:1, in both the light and dark themes. The theme follows the device by default; an Auto/Light/Dark switch persists the choice per browser and is hidden without JavaScript. The sticky remediation-slot bar does not hide the focused element (2.4.11). |
| Typography and family strip | UI and body text use self-hosted Inter (Latin subset, SIL OFL 1.1), and code and labels use self-hosted IBM Plex Mono (R12). Every page starts with a thin Bearing Quest family strip above the masthead. It holds the full-colour Bearing Quest lockup, a self-hosted static SVG with alt text "Bearing Quest", and the text "project family". The strip has fixed dark colors in both themes, its text is at least 4.5:1 against its background, and it contains nothing focusable, so the skip link stays the first tab stop. The footer carries no family line. Bearing Quest is a project family; the site never describes it as a company. |
| Maintainability | Python 3.14 (the newest GA Lambda managed runtime as of Oct 2026), fully typed; mypy strict on `risk_trainer/domain` and `risk_trainer/content`; test coverage ≥ 85% on the domain and content packages. |
| Error handling | Typed domain exceptions; no stack traces shown to users; error pages show a correlation ID that matches the logs. |

## 7. Scoring model

For each finding:

| Learner treatment | Points |
|---|---|
| Equals the key's `preferred` | 2 |
| In the key's `acceptable` list (not preferred) | 1 |
| Anything else | 0 |

The acceptance approver adjusts points whenever the learner chose `accept` and `accept` scored above zero:
- approver in `approvers.correct` → no change
- approver in `approvers.acceptable` → −1 (floor 0)
- any other approver → 0 for that finding

Total = sum of points; maximum = 2 × number of findings. The same inputs always produce the same score.

## 8. MCP tool contracts

All tools take and return JSON validated with Pydantic. Errors return `{"error": {"code": "<code>", "message": "<plain words>"}}`.

### 8.1 Authoring server (local, R16–R17)

| Tool | Input | Output |
|---|---|---|
| `get_schema` | none | JSON Schema of the scenario model, plus the treatment and approver codes with their labels |
| `list_scenarios` | `status` (optional: draft, approved, retired) | `{scenarios: [{id, version, status, title, difficulty, valid: true}], invalid: [{path, valid: false, error_count}]}`. Files that fail validation are always listed under `invalid`, whatever the filter. |
| `validate_scenario` | `yaml_text` (≤ 30,000 characters) | `{valid: bool, errors: [{path, message}]}` |
| `score_answers` | Exactly one of `scenario_id` (a draft or approved scenario) or `yaml_text`; `answers: [{finding_id, treatment, approver?}]`. Same rules as the web exercise (one answer per finding, an approver for `accept`, the remediation-slot limit), except that no rationale is taken. | `{points, max_points, per_finding: [{finding_id, points, preferred}]}` |
| `save_draft` | `yaml_text`; `overwrite` (optional, default false) | `{saved: bool, path, replaced: bool, errors: [...]}`, plus `message` when a draft was replaced (writes only under `content/drafts/`) |

### 8.2 Learner server (remote, R19–R20)

| Tool or prompt | Input | Output |
|---|---|---|
| `list_scenarios` | none | Approved scenarios: `[{id, title, difficulty, estimated_minutes}]` |
| `get_scenario` | `scenario_id` | Context, capacity and findings. No answer-key fields. |
| `submit_answers` | `scenario_id`; `answers: [{finding_id, treatment, approver?, rationale?}]` (rationale 10–600 chars, required for `accept`, optional otherwise) | Score (Section 7), per-finding comparison, expert rationale, key considerations, common traps, job tip and/or exam tip |
| `coach_me` (prompt) | `scenario_id` | The coaching instructions in Appendix B, to be used with the `submit_answers` result |

## 9. Definition of done for v1 launch

1. At least 5 approved scenarios (2 foundational, 2 intermediate, 1 advanced). Across them, each of the four responses is the preferred answer for at least one finding, and each scenario is fact-checked with sources listed in its approval pull request.
2. All CI checks green; coverage targets met; every review conversation resolved on every merged pull request (the branch ruleset enforces this).
3. Deployed through the approved pipeline; edge protection, headers, alarms and the budget have been checked by hand.
4. The read-only smoke checks (R14) pass against the deployed URL after each apply. Completing a scenario and seeing the score and debrief is covered by the local Playwright suite, so production peer counts hold only learner attempts.
5. The owner has completed every scenario on a phone.

v1 launches after groups 5.1–5.3. The scenarios may be drafted in a Claude chat.

**v1.1 (after launch):** group 5.4. The authoring MCP server has been verified in MCP Inspector and used from Claude to draft at least 2 new scenarios.

**v1.2 (stretch):** group 5.5, the learner MCP endpoint.

**v1.3:** group 5.6, the public stats page (R22). It doesn't depend on group 5.5.

## 10. Deferred decisions (resolve in the Claude Code plan for the group that needs them)

- ~~Lambda adapter~~ Resolved (v1.6): Mangum. It's a pure-Python ASGI handler for Function URL events, needs no layer and no server process, and is maintained (0.22.0).
- ~~Origin pattern~~ Resolved (v1.6): CloudFront → Lambda Function URL (auth `NONE`), with a secret origin header that the app checks (R12). OAC would need an `x-amz-content-sha256` header on every POST, which plain forms can't send. API Gateway isn't always-free and can't be limited to CloudFront either.
- ~~Free flat-rate plan with this origin~~ Resolved (v1.7): the distribution uses only plan-supported features (managed policies, 2 cache behaviors, 1 WAF rule, no logging). Confirmed when the owner subscribes (R12).
- Group 5.5 transport details on Lambda: stateless streamable HTTP with JSON responses; how cold starts affect the connector.
- Custom domain (Route 53 + ACM) or the default CloudFront domain. Default for v1, because a domain costs money.

## 11. Out of scope for v1 (v2 candidates)

Instructor mode with class codes; learner progress with accounts; timed "exam mode"; additional exercise types (quantitative ALE/SLE/ARO calculations, BIA/RTO prioritization); scenario import from vulnerability scanner output; in-app AI critique through a paid LLM API.

---

## Appendix A — Scenario schema (reference)

The authoritative model is the Pydantic class built in group `content-foundation`. A complete example is in `content/drafts/rt-001-five-findings.yaml`.

```yaml
id: string                 # kebab-case, unique, e.g. rt-001-five-findings
version: int               # bump on any learner-visible change
status: draft | approved | retired
title: string
difficulty: foundational | intermediate | advanced
estimated_minutes: int
cissp_domains: [int]       # 1-8
learning_objectives: [string]
context:
  organization: string     # fictional
  industry: string
  size: string
  risk_appetite: string
  constraints: [string]
  capacity:
    remediation_slots: int # default 2
findings:                  # exactly 5 in v1
  - id: F1..F5
    title: string
    description: string
    asset: string
    exposure: internet_facing | internal | segmented | third_party | process
    signals:
      cvss_base: float | null       # null for misconfigurations or non-CVE risks
      known_exploited: bool
      data_involved: string | null
      compensating_controls_available: [string]
      remediation_effort: low | medium | high
      business_owner: string
answer_key:
  findings:
    F1:
      preferred: <treatment>
      acceptable: [<treatment>]      # must include preferred
      approvers:                     # required if accept is preferred or acceptable
        correct: [<approver>]
        acceptable: [<approver>]
      key_considerations: [string]   # 2-4, used by the debrief and MCP coaching
      expert_rationale: string       # owner's voice, <= 120 words
      why_not: {<treatment>: string} # optional, explains tempting wrong answers
  overall_debrief: string
  common_traps: [string]
  exam_tip: string | null       # required for intermediate and advanced
  job_tip: string | null        # required for foundational; an on-the-job tip
reviewed_by: string | null
reviewed_on: date | null
```

## Appendix B — `coach_me` prompt (learner MCP server)

Returned by the learner server's `coach_me` prompt. It lives in `prompts/coach_me.md` and is versioned with the code.

```
You are coaching a learner through a Risk Trainer scenario, the way a
security manager coaches a new analyst.

Flow: call get_scenario and present the context and the five findings.
Ask the learner for a treatment (avoid, mitigate by remediating, mitigate
with a compensating control, transfer, accept) for each finding, and a
one-line reason (required for accept, optional otherwise). If they choose
accept, ask who approves it. Respect the
remediation capacity. Then call submit_answers with their answers.

After scoring:
- Do not re-score and do not argue with the answer key.
- Coach the reasoning: compare each reason with the key considerations
  that submit_answers returned.
- Use only facts from the scenario and the submit_answers result. Add no
  outside facts, CVE identifiers, statistics or product names.
- Use CISSP risk-response terms. "Fix" and "reduce" are forms of
  mitigation.
- Reinforce the manager mindset: risk is likelihood x impact, CVSS is not
  risk, capacity is finite, and the risk owner accepts risk, not security.
- Be direct and brief: a few sentences per finding, then one overall tip.
```
