variable "name" {
  description = "A short name for the site and its resources, e.g. covid-wall-dev."
  type        = string
}

variable "cloudfront_distribution_arn" {
  description = "The site's CloudFront distribution: the only caller the function answers."
  type        = string
}

variable "deletion_protection" {
  description = "Keep the messages table from being deleted until this is turned off."
  type        = bool
  default     = true
}

variable "log_retention_days" {
  description = "How long the function's logs are kept. They hold no message text."
  type        = number
  default     = 30
}

variable "max_concurrency" {
  description = "Most messages handled at once (reserved concurrency), or null for no cap."
  type        = number
  default     = null
}

variable "tags" {
  type    = map(string)
  default = {}
}
