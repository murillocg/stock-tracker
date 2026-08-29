#!/usr/bin/env bash
#
# Create the S3 bucket and DynamoDB table that hold Terraform's state and lock.
#
# Deliberately NOT managed by Terraform. A config that manages its own state
# backend can be asked to delete the bucket its state lives in, which is a bad
# afternoon. These two resources are created once, by hand, and left alone.
#
#   ./bootstrap-state.sh
#
# Idempotent: safe to re-run.
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="stock-tracker-tfstate-${ACCOUNT}"
LOCK_TABLE="stock-tracker-tflock"

echo "==> account ${ACCOUNT}, region ${REGION}"

if aws s3api head-bucket --bucket "${BUCKET}" 2>/dev/null; then
  echo "    bucket ${BUCKET} already exists"
else
  echo "==> creating bucket ${BUCKET}"
  # us-east-1 is the one region that rejects a LocationConstraint.
  if [[ "${REGION}" == "us-east-1" ]]; then
    aws s3api create-bucket --bucket "${BUCKET}" --region "${REGION}" >/dev/null
  else
    aws s3api create-bucket --bucket "${BUCKET}" --region "${REGION}" \
      --create-bucket-configuration "LocationConstraint=${REGION}" >/dev/null
  fi
fi

# Versioning is the real safety net: it turns a corrupted or truncated state file
# from a catastrophe into a restore.
aws s3api put-bucket-versioning --bucket "${BUCKET}" \
  --versioning-configuration Status=Enabled

aws s3api put-bucket-encryption --bucket "${BUCKET}" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

# State holds every API token in clear text. This bucket must never be public.
aws s3api put-public-access-block --bucket "${BUCKET}" \
  --public-access-block-configuration \
  'BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true'

if aws dynamodb describe-table --table-name "${LOCK_TABLE}" --region "${REGION}" >/dev/null 2>&1; then
  echo "    lock table ${LOCK_TABLE} already exists"
else
  echo "==> creating lock table ${LOCK_TABLE}"
  # Terraform 1.5 needs a DynamoDB table for locking; S3-native locking only
  # arrived in 1.10. PAY_PER_REQUEST, so it costs nothing when idle.
  aws dynamodb create-table --table-name "${LOCK_TABLE}" --region "${REGION}" \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST >/dev/null
  aws dynamodb wait table-exists --table-name "${LOCK_TABLE}" --region "${REGION}"
fi

echo
echo "==> done. Backend config:"
echo "      bucket         = \"${BUCKET}\""
echo "      dynamodb_table = \"${LOCK_TABLE}\""
