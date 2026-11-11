# Bootstrap (owner only)

This module creates what the deploy pipeline needs before it can run. The owner applies it once with the `rt-admin` profile. Agents never edit it or run it (`AGENTS.md`).

| Resource | Purpose |
|---|---|
| S3 bucket `risk-trainer-tfstate-<account>` | Terraform state for `bootstrap/` and `prod/`. Versioned, SSE-S3, public access blocked, TLS only, native lock files (R11). `prevent_destroy` is on. |
| GitHub OIDC provider | Audience `sts.amazonaws.com`. Skip it with `create_oidc_provider = false` if the account already has one. |
| Role `risk-trainer-gha-plan` | Trusted only by `repo:BearingQuest@352613740/risk-trainer@1398551921:ref:refs/heads/main`. Read access to the app resources. On state it can only take the lock file. |
| Role `risk-trainer-gha-deploy` | Trusted only by `repo:BearingQuest@352613740/risk-trainer@1398551921:environment:prod`. Creates and updates `risk-trainer-*` resources. |
| Policy `risk-trainer-app-boundary` | Permissions boundary for the app's Lambda role. The deploy role can only create that role with this boundary attached. |

Guardrails on both roles deny four things:
- changing the `risk-trainer-gha-*` roles and policies, the boundary or the OIDC provider
- removing a permissions boundary or attaching managed policies
- any `pricingplanmanager` action
- writing to the bootstrap state

**OIDC subject format.** This repository uses GitHub's immutable subject format, `repo:<owner>@<owner_id>/<name>@<repo_id>:…`, so the trust policies match on the numeric IDs as well as the names (`github_owner_id`, `github_repository_id`). It's safer because names can be reused: if the account or repository is renamed or deleted, someone else could take the old name and mint a token with the old `repo:BearingQuest/risk-trainer:…` subject. They can't get the original IDs. To find the IDs: `gh api repos/BearingQuest/risk-trainer --jq '.owner.id, .id'`.

Everything is in us-east-2, except that the deploy role's WAF permissions name the us-east-1 web ACL ARN, because a CloudFront-scope web ACL must live there.

## First apply

Run from the repository root, signed in with `aws sso login --profile rt-admin`.

1. **Create the two secrets.** This also creates the `aws/ssm` KMS key that the roles are scoped to. The values are generated inline, so they're never shown or typed.
   ```sh
   aws ssm put-parameter --profile rt-admin --region us-east-2 --type SecureString --tier Standard \
     --name /risk-trainer/prod/session-secret --value "$(openssl rand -base64 48)"
   aws ssm put-parameter --profile rt-admin --region us-east-2 --type SecureString --tier Standard \
     --name /risk-trainer/prod/origin-verify  --value "$(openssl rand -hex 32)"
   ```
2. **Run the read-only checks.**
   ```sh
   aws lambda get-account-settings --profile rt-admin --region us-east-2   # UnreservedConcurrentExecutions must be >= 105
   aws dynamodb list-tables --profile rt-admin --region us-east-2          # other tables share the 25 RCU / 25 WCU free tier
   aws iam list-open-id-connect-providers --profile rt-admin               # if GitHub's is listed, add -var create_oidc_provider=false
   ```
3. **Apply on local state.** The bucket doesn't exist yet, so a gitignored override file switches the backend to local.
   ```sh
   cd infra/bootstrap
   export AWS_PROFILE=rt-admin
   export TF_VAR_account_id="$(aws sts get-caller-identity --query Account --output text)"
   printf 'terraform {\n  backend "local" {}\n}\n' > local_override.tf
   terraform init
   terraform plan -out bootstrap.tfplan
   terraform apply bootstrap.tfplan
   ```
4. **Move the state into the bucket**, then delete the local copies.
   ```sh
   BUCKET="$(terraform output -raw state_bucket)"
   rm local_override.tf bootstrap.tfplan
   terraform init -migrate-state -backend-config="bucket=${BUCKET}"
   rm -f terraform.tfstate terraform.tfstate.backup
   ```
5. **Configure GitHub.** These are read by the deploy workflow in PR 3.
   ```sh
   gh variable set TF_STATE_BUCKET   --body "${BUCKET}"
   gh variable set AWS_PLAN_ROLE_ARN --body "$(terraform output -raw plan_role_arn)"
   gh variable set AWS_DEPLOY_ROLE_ARN --env prod --body "$(terraform output -raw deploy_role_arn)"
   gh secret set ALERT_EMAIL --env prod   # prompts for the value; it's never echoed
   ```
   In **Settings → Environments → prod**, make yourself a required reviewer and limit deployment branches to `main`.

## Later changes

The owner edits this module and applies it with `terraform init -backend-config="bucket=${BUCKET}"`, then `terraform plan -out …`, then `terraform apply …`, using `rt-admin`. Tests run in CI with a mocked provider (`terraform -chdir=infra/bootstrap test`), so they make no AWS calls.
