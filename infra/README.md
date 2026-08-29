# infra

Terraform for Phase 0: the two DynamoDB tables, the collector Lambda, and the
daily EventBridge schedule. API Gateway, SES and S3/CloudFront arrive in
Phases 1–2.

State is **local** (`terraform.tfstate`, gitignored). A remote S3 backend would
mean a bucket and a lock table running permanently, which defeats the purpose.
Back the file up if it matters — it is the only record of what exists, and it
contains your API tokens.

## Pick the AWS account first

If you already use the AWS CLI for other projects, do this before anything else.
A named profile keeps this project's credentials separate from everything already
configured.

```bash
# Back up what you have. Cheap insurance.
cp -a ~/.aws ~/.aws.backup-$(date +%F)

# --profile creates a NEW section. Bare `aws configure`, with no --profile,
# overwrites [default] instead — that is the one command to avoid.
aws configure --profile stock-tracker

# Note the account id; it goes in terraform.tfvars.
aws sts get-caller-identity --profile stock-tracker
```

Credential resolution runs highest-first: `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`
env vars, then `AWS_PROFILE`, then `[default]`. An env var already exported in your
shell silently outranks the profile named in `terraform.tfvars` — which is exactly
what `allowed_account_ids` exists to catch.

## First deploy

```bash
# 1. Cross-compile the dependencies and stage the code
backend/scripts/build_lambda.sh

# 2. Account, then tokens
cd infra
cp terraform.tfvars.example terraform.tfvars
$EDITOR terraform.tfvars      # aws_profile + allowed_account_ids first

# 3. Review, then apply
terraform init
terraform plan                # confirm 11 to add, 0 to change, 0 to destroy
terraform apply
```

If the credentials resolve to any account other than the one you listed,
`plan` fails with `AWS account ID not allowed: <id>` and creates nothing.

Keep `schedule_enabled = false` until a manual run has worked.

## Redeploying after a code change

`build_lambda.sh` then `terraform apply`. Terraform hashes the build output, so
it re-uploads only what actually changed — usually just the 128 KB `shared`
layer rather than the 8 MB dependency layer.

## Seeding your first stock

Nothing collects until the registry has an entry. Note `quoteProvider` and
`fundamentalsProvider` are separate: no free source covers both.

```bash
aws dynamodb put-item \
  --region us-east-1 \
  --table-name stock-tracker-Stocks \
  --item '{
    "ticker":               {"S": "PETR4"},
    "name":                 {"S": "Petrobras PN"},
    "market":               {"S": "B3"},
    "currency":             {"S": "BRL"},
    "quoteProvider":        {"S": "BRAPI"},
    "fundamentalsProvider": {"S": "BOLSAI"},
    "listType":             {"S": "PORTFOLIO"},
    "category":             {"S": "CYCLICAL"}
  }'
```

## Running it by hand

`terraform output invoke_command` prints this with your real names filled in:

```bash
aws lambda invoke \
  --function-name stock-tracker-collector \
  --cli-binary-format raw-in-base64-out \
  --payload '{"tickers":["PETR4"]}' \
  /dev/stdout
```

The response is the `CollectionReport`: a per-ticker outcome plus a summary of
`COLLECTED` / `PARTIAL` / `SKIPPED` / `NOT_FOUND` / `FAILED`. `PARTIAL` means the
price stored but bolsai did not answer.

Logs: `terraform output tail_logs_command`.

## Things worth knowing

**Architecture must match.** The Lambda runs `arm64`, so `build_lambda.sh` pins
`manylinux2014_aarch64`. Change one without the other and the function dies at
import with `No module named 'pydantic_core._pydantic_core'` — the wheel is
native code, and a macOS build will upload perfectly happily.

**Tokens live in Lambda environment variables**, encrypted at rest but visible to
anyone with console access to the function, and present in `terraform.tfstate`.
Acceptable for a single-user personal account. The upgrade path is SSM Parameter
Store (still free) read at cold start.

**Log retention is 14 days.** Auto-created log groups keep logs forever, which is
the one thing in this stack that quietly accrues cost; the group is declared
explicitly to avoid that.

**Point-in-time recovery is off** by default to stay in the free tier. Consider
turning it on for `DailySnapshots`: those rows cannot be rebuilt, because no free
provider serves historical prices. Lose the table and the change1w/1m/6m/1y
series restarts from zero.

**Retries are safe.** The schedule retries twice. Snapshots are keyed by
`(ticker, date)` and the collector skips tickers already stored for the date, so
a retry neither duplicates rows nor re-spends API quota.

## Tearing down

```bash
terraform destroy
```

Deletes the tables and all collected history. See the PITR note above.
