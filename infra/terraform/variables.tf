variable "environment" {
  description = "development | staging | production"
  type        = string
  validation {
    condition     = contains(["development", "staging", "production"], var.environment)
    error_message = "environment deve ser development, staging ou production."
  }
}
variable "region" {
  type    = string
  default = "sa-east-1"
}
variable "domain_name" {
  description = "Domínio público (ex.: atende.seubar.com.br). Frontend e API ficam na mesma origem."
  type        = string
}
variable "hosted_zone_id" {
  description = "Zona Route 53 do domínio (validação dos certificados e registro DNS)."
  type        = string
}
variable "api_image_tag" {
  description = "Tag da imagem da API no ECR (ex.: SHA do commit)."
  type        = string
}
variable "api_desired_count" {
  type    = number
  default = 2
}
variable "api_max_count" {
  type    = number
  default = 6
}
variable "api_cpu" {
  type    = number
  default = 512
}
variable "api_memory" {
  type    = number
  default = 1024
}
variable "db_instance_class" {
  type    = string
  default = "db.t4g.small"
}
variable "db_multi_az" {
  type    = bool
  default = false
}
variable "db_backup_retention_days" {
  type    = number
  default = 7
}
variable "redis_node_type" {
  type    = string
  default = "cache.t4g.micro"
}
variable "alarm_email" {
  description = "E-mail que recebe os alarmes do CloudWatch (vazio = sem assinatura)."
  type        = string
  default     = ""
}
variable "vapid_subject" {
  type    = string
  default = "mailto:contato@example.com"
}

locals {
  name = "andripa-${var.environment}"
  tags = { Project = "andripa", Environment = var.environment, ManagedBy = "terraform" }
  azs  = slice(data.aws_availability_zones.available.names, 0, 2)
}

data "aws_availability_zones" "available" { state = "available" }
data "aws_caller_identity" "current" {}
