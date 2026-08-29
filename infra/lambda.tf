# Artefacts come from backend/scripts/build_lambda.sh. Run it before apply —
# Terraform zips whatever is in backend/build/ and will fail the plan if it is
# missing.

locals {
  build_dir = "${path.module}/../backend/build"
}

data "aws_caller_identity" "current" {}

# Two layers rather than one. Dependencies change on the rare occasion we add a
# package; `shared` changes constantly. Splitting them keeps the day-to-day
# deploy at 128 KB instead of 8 MB.
data "archive_file" "dependencies_layer" {
  type        = "zip"
  source_dir  = "${local.build_dir}/dependencies"
  output_path = "${local.build_dir}/dependencies.zip"
}

data "archive_file" "shared_layer" {
  type        = "zip"
  source_dir  = "${local.build_dir}/shared"
  output_path = "${local.build_dir}/shared.zip"
}

data "archive_file" "collector" {
  type        = "zip"
  source_dir  = "${local.build_dir}/collector"
  output_path = "${local.build_dir}/collector.zip"
}

resource "aws_lambda_layer_version" "dependencies" {
  layer_name          = "${var.project_name}-dependencies"
  description         = "pydantic + httpx, built for ${local.lambda_architecture}"
  filename            = data.archive_file.dependencies_layer.output_path
  source_code_hash    = data.archive_file.dependencies_layer.output_base64sha256
  compatible_runtimes = [local.lambda_runtime]

  compatible_architectures = [local.lambda_architecture]
}

resource "aws_lambda_layer_version" "shared" {
  layer_name          = "${var.project_name}-shared"
  description         = "shared/ package: models, providers, indicators, repository"
  filename            = data.archive_file.shared_layer.output_path
  source_code_hash    = data.archive_file.shared_layer.output_base64sha256
  compatible_runtimes = [local.lambda_runtime]

  compatible_architectures = [local.lambda_architecture]
}

locals {
  lambda_runtime = "python3.13"

  # arm64 (Graviton) is roughly 20% cheaper per GB-second than x86_64 and is
  # covered by the same free tier. It is also why build_lambda.sh pins
  # manylinux2014_aarch64 — the two must agree or pydantic_core fails to import.
  lambda_architecture = "arm64"
}

# Created explicitly rather than letting Lambda auto-create it on first
# invocation, because an auto-created group retains logs forever.
resource "aws_cloudwatch_log_group" "collector" {
  name              = "/aws/lambda/${var.project_name}-collector"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "collector" {
  function_name = "${var.project_name}-collector"
  role          = aws_iam_role.collector.arn
  runtime       = local.lambda_runtime
  architectures = [local.lambda_architecture]

  # package.module.function — `collector` resolves from the function zip,
  # `shared` from the layer at /opt/python/. Identical import paths to local dev.
  handler = "collector.handler.lambda_handler"

  filename         = data.archive_file.collector.output_path
  source_code_hash = data.archive_file.collector.output_base64sha256

  timeout     = var.lambda_timeout_seconds
  memory_size = var.lambda_memory_mb

  layers = [
    aws_lambda_layer_version.dependencies.arn,
    aws_lambda_layer_version.shared.arn,
  ]

  environment {
    variables = {
      STOCKS_TABLE           = aws_dynamodb_table.stocks.name
      SNAPSHOTS_TABLE        = aws_dynamodb_table.daily_snapshots.name
      BRAPI_TOKEN            = var.brapi_token
      BOLSAI_API_KEY         = var.bolsai_api_key
      ALPHA_VANTAGE_API_KEY  = var.alpha_vantage_api_key
      ALERT_SENDER           = var.alert_sender
      ALERT_RECIPIENT        = var.alert_recipient
      PROVIDER_DELAY_SECONDS = tostring(var.provider_delay_seconds)
      MARKET_TIMEZONE        = var.market_timezone
    }
  }

  depends_on = [
    aws_iam_role_policy.collector,
    aws_cloudwatch_log_group.collector,
  ]
}
