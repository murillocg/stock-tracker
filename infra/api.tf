# Lambda 2 + API Gateway. Read-only: this role has no PutItem anywhere, so a bug
# in the API cannot touch the data the collector owns.

data "archive_file" "api" {
  type        = "zip"
  source_dir  = "${local.build_dir}/api"
  output_path = "${local.build_dir}/api.zip"
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${var.project_name}-api"
  retention_in_days = var.log_retention_days
}

resource "aws_iam_role" "api" {
  name               = "${var.project_name}-api"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

data "aws_iam_policy_document" "api" {
  statement {
    sid = "ReadTables"

    # GetItem and Query only. The read API is structurally incapable of writing.
    actions = ["dynamodb:GetItem", "dynamodb:Query"]

    resources = [
      aws_dynamodb_table.stocks.arn,
      "${aws_dynamodb_table.stocks.arn}/index/*",
      aws_dynamodb_table.daily_snapshots.arn,
    ]
  }

  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.api.arn}:*"]
  }
}

resource "aws_iam_role_policy" "api" {
  name   = "${var.project_name}-api"
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api.json
}

resource "aws_lambda_function" "api" {
  function_name = "${var.project_name}-api"
  role          = aws_iam_role.api.arn
  runtime       = local.lambda_runtime
  architectures = [local.lambda_architecture]
  handler       = "api.handler.lambda_handler"

  filename         = data.archive_file.api.output_path
  source_code_hash = data.archive_file.api.output_base64sha256

  # Short and small: this one answers a browser, so p99 latency matters more than
  # throughput, and the work is a single Query plus some pure evaluation.
  timeout     = 10
  memory_size = var.api_memory_mb

  layers = [
    aws_lambda_layer_version.dependencies.arn,
    aws_lambda_layer_version.shared.arn,
  ]

  environment {
    variables = {
      STOCKS_TABLE    = aws_dynamodb_table.stocks.name
      SNAPSHOTS_TABLE = aws_dynamodb_table.daily_snapshots.name
      MARKET_TIMEZONE = var.market_timezone

      # Config.from_env() requires these, though the read path never uses them.
      # Empty strings would fail the required() check, so they are passed through.
      BRAPI_TOKEN     = var.brapi_token
      BOLSAI_API_KEY  = var.bolsai_api_key
      ALERT_SENDER    = var.alert_sender
      ALERT_RECIPIENT = var.alert_recipient
    }
  }

  depends_on = [
    aws_iam_role_policy.api,
    aws_cloudwatch_log_group.api,
  ]
}

# HTTP API, not REST API. Roughly a third of the price, lower latency, and it has
# native CORS config — the REST flavour would need a mock OPTIONS integration per
# route just to answer preflight.
resource "aws_apigatewayv2_api" "main" {
  name          = "${var.project_name}-api"
  protocol_type = "HTTP"
  description   = "Read API for the stock tracker frontend."

  cors_configuration {
    # The browser sends an Origin header the CloudFront distribution does not know
    # about yet, so this is left open until the frontend has a real domain. Not a
    # data risk today — every endpoint is read-only and the data is public market
    # figures — but it should be narrowed once the Vue app is deployed.
    allow_origins = var.api_allowed_origins
    allow_methods = ["GET", "OPTIONS"]
    allow_headers = ["content-type"]
    max_age       = 3600
  }
}

resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
}

# The route keys here are the same strings `route()` switches on in handler.py.
# Declared once, matched exactly.
resource "aws_apigatewayv2_route" "list_stocks" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "GET /stocks"
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}

resource "aws_apigatewayv2_route" "get_stock" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "GET /stocks/{ticker}"
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true

  # Throttling is the guardrail that matters on a public endpoint: without it a
  # loop hitting /stocks would bill Lambda invocations and DynamoDB reads until
  # someone noticed.
  default_route_settings {
    throttling_burst_limit = var.api_throttle_burst
    throttling_rate_limit  = var.api_throttle_rate
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_access.arn
    format = jsonencode({
      requestId = "$context.requestId"
      method    = "$context.httpMethod"
      route     = "$context.routeKey"
      status    = "$context.status"
      latency   = "$context.responseLatency"
      error     = "$context.integrationErrorMessage"
    })
  }
}

resource "aws_cloudwatch_log_group" "api_access" {
  name              = "/aws/apigateway/${var.project_name}"
  retention_in_days = var.log_retention_days
}

# API Gateway is a separate principal; without this it gets AccessDenied invoking
# the function. `source_arn` scopes the grant to this API rather than any caller.
resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowInvokeFromApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}
