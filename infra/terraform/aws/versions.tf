terraform {
  required_version = ">= 1.9.0, < 2.0.0"

  backend "s3" {}

  required_providers {
    aws = {
      source = "hashicorp/aws"
      # EKS module v20 still declares launch-template blocks removed in AWS v6.
      # Keep the provider on the latest compatible v5 release until the module
      # and this root are upgraded together and revalidated.
      version = ">= 5.80, < 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.7"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.tags
  }
}
