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

variable "aws_profile" {
  description = <<-EOT
    Named profile from ~/.aws/credentials to deploy with. Create it WITHOUT
    disturbing anything already there:

        aws configure --profile stock-tracker

    Bare `aws configure`, with no --profile, overwrites [default] instead.
    Leave null to fall back to the usual environment/default resolution.
  EOT
  type        = string
  default     = null
}

variable "allowed_account_ids" {
  description = <<-EOT
    Account IDs this stack may deploy into. Terraform hard-fails if the resolved
    credentials belong to anything else, which is what stops a stale AWS_PROFILE
    or an exported AWS_ACCESS_KEY_ID from creating resources in the wrong place.

    Find yours with:  aws sts get-caller-identity --profile stock-tracker

    Empty list disables the check. Set it — it is the cheapest guardrail here.
  EOT
  type        = list(string)
  default     = []
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

variable "alpha_vantage_api_key" {
  description = <<-EOT
    Alpha Vantage key, for US tickers. Free at alphavantage.co/support/#api-key.
    25 requests/day, and we spend 2 per stock, so this caps US holdings around a
    dozen. Unlike the B3 sources it does supply dividend yield and payout ratio.
  EOT
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

variable "market_timezone" {
  description = <<-EOT
    Timezone that decides which trading day a run belongs to. Lambda's clock is
    UTC and the collector runs after the B3 close, so date.today() would stamp
    every snapshot with tomorrow — and that date is the sort key of the whole
    time series. Normally the same value as schedule_timezone.
  EOT
  type        = string
  default     = "America/Sao_Paulo"
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
  description = <<-EOT
    Pause before EVERY upstream call — not merely between tickers, because Alpha
    Vantage serves both the quote and the fundamentals for a US stock and rejects
    anything faster than one request per second.

    1.5 rather than 1.0: the limit is stated as "1 request per second", so sitting
    exactly on the boundary is asking to be throttled by clock skew alone.
  EOT
  type        = number
  default     = 1.5
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
    PITR on DailySnapshots and Transactions. ON by default.

    These two tables are the only things here that CANNOT be rebuilt. No free
    provider serves historical prices, so a lost DailySnapshots means the
    change1w/1m/6m/1y series — and the headroom trend built on it — starts from
    zero again and waits a year to be useful. The ledger is worse: it was
    reconciled by hand against broker statements, and the Avenue quantities
    cannot be recovered from the statements at all.

    It was off to stay inside the free tier. PITR bills on table size, and these
    tables hold kilobytes; the cost of the alternative is a year of waiting.
  EOT
  type        = bool
  default     = true
}

variable "api_memory_mb" {
  description = "Read API memory. Small: one Query plus pure evaluation."
  type        = number
  default     = 256
}

variable "api_allowed_origins" {
  description = <<-EOT
    CORS origins for the read API. Open until the Vue app has a CloudFront domain
    to name here. Every endpoint is read-only public market data, so this is not
    a data risk today, but narrow it once the frontend is deployed.
  EOT
  type        = list(string)
  default     = ["*"]
}

variable "api_throttle_rate" {
  description = <<-EOT
    Steady-state requests/second. A public endpoint with no throttle can be
    looped by anyone; this caps what that could cost. One user refreshing a page
    needs a fraction of this.
  EOT
  type        = number
  default     = 20
}

variable "api_throttle_burst" {
  description = "Burst allowance above the steady rate."
  type        = number
  default     = 40
}

variable "cloudfront_price_class" {
  description = <<-EOT
    Which edge locations serve the app. PriceClass_All includes South America, so
    a viewer in Brazil is served from Sao Paulo rather than Miami. CloudFront's
    always-free tier covers 1 TB/month regardless of class, and this app serves a
    few megabytes, so the cheaper classes save nothing real and cost latency.
  EOT
  type        = string
  default     = "PriceClass_All"
}

variable "api_extra_allowed_origins" {
  description = "Origins allowed alongside the CloudFront domain. Vite dev server by default."
  type        = list(string)
  default     = ["http://localhost:5173"]
}
