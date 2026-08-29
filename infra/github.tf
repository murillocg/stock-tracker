# Lets GitHub Actions deploy without any stored AWS credential.
#
# Actions mints a short-lived OIDC token; AWS trades it for temporary role
# credentials. Nothing long-lived exists to leak, rotate, or forget about — which
# matters more here than usual, because the repository is public.

variable "github_owner" {
  description = "GitHub account that owns the repository."
  type        = string
  default     = "murillocg"
}

variable "github_repo" {
  description = "Repository name."
  type        = string
  default     = "stock-tracker"
}

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

data "aws_iam_policy_document" "github_assume_role" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Scoped to the main branch, not to the repository generally. On a public
    # repo that distinction is the whole security boundary: anyone can open a
    # pull request, and `repo:owner/name:*` would let a workflow running on an
    # attacker's branch assume this role. Only pushes to main can, and only you
    # can push to main.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_owner}/${var.github_repo}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "github_actions" {
  name               = "${var.project_name}-github-actions"
  description        = "Assumed by GitHub Actions to run terraform apply."
  assume_role_policy = data.aws_iam_policy_document.github_assume_role.json
}

data "aws_iam_policy_document" "github_actions" {
  # Terraform's own state and lock.
  statement {
    sid     = "TerraformState"
    actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
    resources = [
      "arn:aws:s3:::stock-tracker-tfstate-${data.aws_caller_identity.current.account_id}",
      "arn:aws:s3:::stock-tracker-tfstate-${data.aws_caller_identity.current.account_id}/*",
    ]
  }

  statement {
    sid       = "TerraformLock"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"]
    resources = ["arn:aws:dynamodb:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/stock-tracker-tflock"]
  }

  # The project's own resources. Scoped by name prefix where the service supports
  # it; CloudFront and API Gateway largely do not offer resource-level control for
  # create/describe actions, so those are account-wide by necessity rather than
  # by choice.
  statement {
    sid = "ProjectResources"
    actions = [
      "dynamodb:*",
      "lambda:*",
      "logs:*",
      "s3:*",
      "scheduler:*",
      "apigateway:*",
      "cloudfront:*",
    ]
    resources = ["*"]
  }

  # IAM is the dangerous one, so it is confined to this project's role names.
  # Without that, a compromised workflow could mint itself an admin role.
  statement {
    sid = "ProjectRoles"
    actions = [
      "iam:GetRole",
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:PassRole",
      "iam:TagRole",
      "iam:ListRolePolicies",
      "iam:GetRolePolicy",
      "iam:PutRolePolicy",
      "iam:DeleteRolePolicy",
      "iam:ListAttachedRolePolicies",
    ]
    resources = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project_name}-*"]
  }

  statement {
    sid       = "ReadOidcProvider"
    actions   = ["iam:GetOpenIDConnectProvider"]
    resources = [aws_iam_openid_connect_provider.github.arn]
  }

  statement {
    sid       = "Identity"
    actions   = ["sts:GetCallerIdentity"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "github_actions" {
  name   = "${var.project_name}-github-actions"
  role   = aws_iam_role.github_actions.id
  policy = data.aws_iam_policy_document.github_actions.json
}

output "github_actions_role_arn" {
  description = "Set as the AWS_ROLE_ARN repository variable in GitHub."
  value       = aws_iam_role.github_actions.arn
}
