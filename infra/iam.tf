# Least privilege throughout: the collector can read and write exactly two tables
# and write to exactly one log group. No managed policies, no wildcards on
# resources.

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "collector" {
  name               = "${var.project_name}-collector"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

data "aws_iam_policy_document" "collector" {
  statement {
    sid = "ReadWriteTables"

    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:Query",
    ]

    # The GSI is a separate ARN. Granting the table alone would let get_item and
    # put_item through but fail list_by_type with AccessDenied — an easy hour to
    # lose, since the error surfaces only on that one code path.
    resources = [
      aws_dynamodb_table.stocks.arn,
      "${aws_dynamodb_table.stocks.arn}/index/*",
      aws_dynamodb_table.daily_snapshots.arn,
    ]
  }

  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.collector.arn}:*"]
  }
}

resource "aws_iam_role_policy" "collector" {
  name   = "${var.project_name}-collector"
  role   = aws_iam_role.collector.id
  policy = data.aws_iam_policy_document.collector.json
}

# --- EventBridge Scheduler ---------------------------------------------------
# The scheduler is a separate principal and needs its own role to invoke the
# function. It cannot borrow the Lambda's.

data "aws_iam_policy_document" "scheduler_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }

    # Without this, any AWS account whose scheduler is pointed at this role ARN
    # could assume it. Pinning the source account closes that confused-deputy
    # hole; it costs one block and is the sort of thing worth doing by reflex.
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${var.project_name}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume_role.json
}

data "aws_iam_policy_document" "scheduler_invoke" {
  statement {
    sid       = "InvokeCollector"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.collector.arn]
  }
}

resource "aws_iam_role_policy" "scheduler_invoke" {
  name   = "${var.project_name}-scheduler-invoke"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler_invoke.json
}
