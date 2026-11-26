variable "name" {
  description = "A short name for the site and its resources, e.g. covid-wall-dev."
  type        = string
}

variable "site" {
  description = "The site's short name in alerts: dev or prod."
  type        = string
}

variable "site_url" {
  description = "Where visitors reach the site, e.g. https://dev.covidwall.co.uk."
  type        = string
}

variable "site_bucket" {
  description = "The bucket the site is served from."
  type        = string
}

variable "alert_email" {
  description = "Where alerts are emailed. AWS sends a confirmation link first; nothing arrives until it is clicked."
  type        = string
}

variable "alert_phone" {
  description = "A phone number in E.164 form (+447700900000) for SMS alarms, or null for none."
  type        = string
  default     = null
}

variable "check_every_minutes" {
  description = "How often the full check runs."
  type        = number
  default     = 5
}

variable "tags" {
  type    = map(string)
  default = {}
}
