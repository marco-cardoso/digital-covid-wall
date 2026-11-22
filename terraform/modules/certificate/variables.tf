variable "domain_name" {
  description = "The main name on the certificate."
  type        = string
}

variable "subject_alternative_names" {
  description = "Other names the certificate should cover."
  type        = list(string)
  default     = []
}

variable "zone_id" {
  description = "The Route 53 zone that holds the domain, where the validation records go."
  type        = string
}

variable "tags" {
  type    = map(string)
  default = {}
}
