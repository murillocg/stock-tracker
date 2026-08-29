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

  default_tags {
    tags = {
      Project   = var.project_name
      ManagedBy = "terraform"
    }
  }
}
