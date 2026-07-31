variable "location" {
  description = "Azure region. Must be a region where Static Web Apps Free tier is available."
  type        = string
  default     = "westeurope"
}

variable "tags" {
  description = "Tags applied to all resources in this project"
  type        = map(string)
  default = {
    project = "writing-contests-finder"
    owner   = "george"
    cost    = "free-tier-only"
  }
}
