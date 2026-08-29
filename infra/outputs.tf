output "stocks_table" {
  description = "Registry table name. Needed to seed your first stock."
  value       = aws_dynamodb_table.stocks.name
}

output "snapshots_table" {
  description = "Time-series table name."
  value       = aws_dynamodb_table.daily_snapshots.name
}

output "collector_function" {
  description = "Collector Lambda name."
  value       = aws_lambda_function.collector.function_name
}

output "log_group" {
  description = "Where collection runs report."
  value       = aws_cloudwatch_log_group.collector.name
}

output "invoke_command" {
  description = "Run the collector by hand, for one ticker, without waiting for the schedule."
  value = join(" ", [
    "aws lambda invoke --region ${var.aws_region}",
    "--function-name ${aws_lambda_function.collector.function_name}",
    "--cli-binary-format raw-in-base64-out",
    "--payload '{\"tickers\":[\"PETR4\"]}'",
    "/dev/stdout"
  ])
}

output "tail_logs_command" {
  description = "Follow the collector's output."
  value       = "aws logs tail ${aws_cloudwatch_log_group.collector.name} --region ${var.aws_region} --follow"
}

output "api_url" {
  description = "Base URL of the read API. The Vue app's VITE_API_URL."
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "api_smoke_command" {
  description = "Fetch the portfolio, already evaluated."
  value       = "curl -s '${aws_apigatewayv2_stage.default.invoke_url}/stocks?listType=PORTFOLIO' | jq ."
}

output "frontend_url" {
  description = "The app. CloudFront's own hostname, HTTPS included."
  value       = "https://${aws_cloudfront_distribution.frontend.domain_name}"
}

output "frontend_bucket" {
  description = "Where the built files live. Private; reachable only via CloudFront."
  value       = aws_s3_bucket.frontend.id
}

output "transactions_table" {
  description = "The trade ledger."
  value       = aws_dynamodb_table.transactions.name
}
