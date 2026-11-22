variable "domain_name" {
  description = "The domain the zone is for, e.g. example.co.uk."
  type        = string
}

variable "records" {
  description = "Records to create, keyed by any unique label. An empty name means the top of the domain."
  type = map(object({
    name   = string
    type   = string
    ttl    = optional(number, 300)
    values = list(string)
  }))
  default = {}
}
