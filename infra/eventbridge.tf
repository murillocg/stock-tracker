# EventBridge *Scheduler*, not an EventBridge rule. Scheduler is the newer
# service and the reason it matters here is `schedule_expression_timezone`: a
# plain rule only understands UTC, so a 20:00 São Paulo run would drift by an
# hour twice a year as DST changes on either side.

resource "aws_scheduler_schedule" "daily_collection" {
  name        = "${var.project_name}-daily-collection"
  description = "Runs the collector once per weekday after B3 closes."
  state       = var.schedule_enabled ? "ENABLED" : "DISABLED"

  # OFF means "fire at exactly this time". The alternative is a jitter window,
  # which exists to spread load across many schedules — pointless for one job,
  # and it would only make the run time unpredictable.
  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression          = var.collection_schedule
  schedule_expression_timezone = var.schedule_timezone

  target {
    arn      = aws_lambda_function.collector.arn
    role_arn = aws_iam_role.scheduler.arn

    # Empty event: the handler defaults `as_of` to today and collects every
    # registered stock. The `tickers` / `asOf` overrides exist for manual runs.
    input = jsonencode({})

    retry_policy {
      # A transient DynamoDB or provider failure raises, and these retries are
      # what recover it. Safe to repeat because collection is idempotent: the
      # snapshot is keyed by (ticker, date), and skip_existing means a retry does
      # not re-spend API quota on tickers already stored.
      maximum_retry_attempts       = 2
      maximum_event_age_in_seconds = 3600
    }
  }
}
