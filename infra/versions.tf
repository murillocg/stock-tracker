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

  # State stays local. A remote S3 backend would mean a bucket and a lock table
  # running permanently, which is the opposite of what this project is for. The
  # trade-off: terraform.tfstate is the only record of what exists, it is
  # gitignored (it holds the API tokens), so back it up if it matters.
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
