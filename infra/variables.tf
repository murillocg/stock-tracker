variable "project_name" {
  description = "Prefix for every resource name."
  type        = string
  default     = "stock-tracker"
}

variable "aws_region" {
  description = <<-EOT
    Region for everything. us-east-1 rather than sa-east-1: this is a once-a-day
    batch job where latency is irrelevant, and sa-east-1 is materially more
    expensive per request. SES also has the widest sandbox coverage here.
  EOT
  type        = string
  default     = "us-east-1"
}

variable "brapi_token" {
  description = "brapi.dev API token. Free plan. Required for any non-demo ticker."
  type        = string
  sensitive   = true
}

variable "bolsai_api_key" {
  description = "usebolsai.com API key, sent as X-API-Key. Free plan is 200 req/day."
  type        = string
  sensitive   = true
}

variable "alert_sender" {
  description = "Verified SES sender address. Unused until Phase 2, but Config requires it."
  type        = string
}

variable "alert_recipient" {
  description = "Where alert emails go."
  type        = string
}

variable "collection_schedule" {
  description = <<-EOT
    When to collect, as an EventBridge Scheduler cron. Weekdays only — B3 is shut
    at weekends and a run would spend API quota re-storing Friday's close.

    Default is 20:00 America/Sao_Paulo: B3's after-market ends 18:25, which gives
    the providers time to publish end-of-day figures.
  EOT
  type        = string
  default     = "cron(0 20 ? * MON-FRI *)"
}

variable "schedule_timezone" {
  description = "IANA timezone for the schedule. Handles DST so the cron does not have to."
  type        = string
  default     = "America/Sao_Paulo"
}

variable "schedule_enabled" {
  description = "Set false to deploy everything without letting it run on its own."
  type        = bool
  default     = true
}

variable "provider_delay_seconds" {
  description = "Pause between upstream calls. Sequential collection, free-tier rate limits."
  type        = number
  default     = 1.0
}

variable "lambda_timeout_seconds" {
  description = <<-EOT
    Collection is sequential: roughly (2 calls + 1s delay) per ticker. 300s covers
    about 60 tickers with a wide margin; bolsai's 200/day quota binds first.
  EOT
  type        = number
  default     = 300
}

variable "lambda_memory_mb" {
  description = <<-EOT
    512 MB, which is about cold start rather than RAM: importing pydantic is the
    slow part, and Lambda scales CPU with memory. The job itself needs far less.
  EOT
  type        = number
  default     = 512
}

variable "log_retention_days" {
  description = <<-EOT
    CloudWatch Logs default to never expiring, which is the one thing in this
    stack that quietly accrues cost forever. 14 days is plenty to debug a run.
  EOT
  type        = number
  default     = 14
}

variable "enable_point_in_time_recovery" {
  description = <<-EOT
    PITR on DailySnapshots. Off by default to stay inside the free tier, but
    consider turning it on: daily snapshots are the one thing here that CANNOT be
    rebuilt: no free provider serves historical prices, so a lost table means the
    change1w/1m/6m/1y series starts from zero again.
  EOT
  type        = bool
  default     = false
}
