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
