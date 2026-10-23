terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.60" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
  # Estado remoto: configure via `terraform init -backend-config=envs/<env>.backend.hcl`
  backend "s3" {}
}

provider "aws" {
  region = var.region
  default_tags { tags = local.tags }
}

# Certificado do CloudFront precisa estar em us-east-1.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
  default_tags { tags = local.tags }
}
