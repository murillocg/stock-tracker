terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }

  # State lives in S3 so that CI can deploy — local state is only reachable from
  # the laptop that holds it. The earlier objection to a remote backend was cost,
  # and it does not survive scrutiny: a versioned bucket holding 90 KB and an
  # on-demand lock table are effectively free.
  #
  # Created by ./bootstrap-state.sh, deliberately outside Terraform: a config that
  # manages its own backend can be asked to delete the bucket its state lives in.
  # Partial config: the bucket name embeds the AWS account id, and this repo is
  # public. Terraform backends cannot read variables, so the remaining settings
  # come from backend.hcl (gitignored) or -backend-config flags in CI.
  #
  #   terraform init -backend-config=backend.hcl
  backend "s3" {
    key     = "stock-tracker/terraform.tfstate"
    region  = "us-east-1"
    encrypt = true
  }
}

provider "aws" {
  region = var.aws_region

  # Which local credentials to use. Naming it here rather than relying on
  # whichever profile happens to be active means this project cannot quietly
  # deploy into another project's account.
  profile = var.aws_profile

  # The seatbelt. Terraform refuses to plan or apply if the resolved credentials
  # belong to an account not listed here — so a stale AWS_PROFILE, an exported
  # AWS_ACCESS_KEY_ID, or a mistyped profile name fails loudly instead of
  # creating eleven resources somewhere you did not intend.
  allowed_account_ids = var.allowed_account_ids

  default_tags {
    tags = {
      Project   = var.project_name
      ManagedBy = "terraform"
    }
  }
}
