# Two tables, both PAY_PER_REQUEST: no provisioned capacity means no hourly cost,
# and a personal portfolio's traffic is a rounding error against the always-free
# 25 GB of storage.

resource "aws_dynamodb_table" "stocks" {
  name         = "${var.project_name}-Stocks"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "ticker"

  # Only KEY attributes are declared. DynamoDB is schemaless everywhere else —
  # `name`, `currency`, `alertRules` and the denormalised `current` map exist in
  # the items without being declared here. Nothing like a relational DDL.
  attribute {
    name = "ticker"
    type = "S"
  }

  attribute {
    name = "listType"
    type = "S"
  }

  global_secondary_index {
    name      = "listType-index"
    hash_key  = "listType"
    range_key = "ticker"

    # The whole point of this index is rendering a list in one query, using the
    # denormalised `current` snapshot. A KEYS_ONLY projection would force a read
    # per stock afterwards and undo that.
    projection_type = "ALL"
  }

  tags = {
    Name = "${var.project_name}-Stocks"
  }
}

resource "aws_dynamodb_table" "daily_snapshots" {
  name         = "${var.project_name}-DailySnapshots"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "ticker"
  range_key    = "date"

  attribute {
    name = "ticker"
    type = "S"
  }

  # ISO 8601 as a string, not a number. It sorts lexicographically in the same
  # order it sorts chronologically, which is what makes the between() range
  # queries behind change1w/1m/6m/1y work on a plain sort key.
  attribute {
    name = "date"
    type = "S"
  }

  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  tags = {
    Name = "${var.project_name}-DailySnapshots"
  }
}
