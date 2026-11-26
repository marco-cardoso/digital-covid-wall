variable "name" {
  description = "A short name for the site and its resources, e.g. covid-wall-prod."
  type        = string
}

variable "aliases" {
  description = "The domain names the site answers on."
  type        = list(string)
}

variable "certificate_arn" {
  description = "A validated ACM certificate covering the aliases. CloudFront only accepts one from us-east-1."
  type        = string
}

variable "zone_id" {
  description = "The Route 53 zone the aliases live in."
  type        = string
}

variable "api" {
  description = <<-EOT
    Optional: send requests for paths matching path_pattern to a Lambda function URL (its host name) instead of the
    bucket, signed by CloudFront, uncached, any method. The function must allow this distribution to invoke it. A
    browser POSTing through it must send the body's SHA-256 (hex) in x-amz-content-sha256.
  EOT
  type = object({
    path_pattern        = string
    function_url_domain = string
  })
  default = null
}

variable "keep_old_versions_days" {
  description = "How long overwritten or deleted files are kept, to restore from."
  type        = number
  default     = 90
}

variable "price_class" {
  description = "PriceClass_100 serves from Europe and North America only, the cheapest."
  type        = string
  default     = "PriceClass_100"
}

variable "tags" {
  type    = map(string)
  default = {}
}
