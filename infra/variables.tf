variable "project_id" {
  type = string
}

variable "region" {
  type    = string
  default = "us-west2"
}

variable "instance_name" {
  type    = string
  default = "student_transcripts"
}

variable "db_name" {
  type    = string
  default = "transcripts"
}

variable "db_user" {
  type    = string
  default = "admin_user"
}

variable "db_password" {
  type        = string
  sensitive   = true
  description = "Postgres password for application user"
}

variable "tier" {
  type    = string
  default = "db-custom-2-4096"
}

variable "disk_size_gb" {
  type    = number
  default = 20
}

variable "enable_public_ip" {
  type    = bool
  default = false
}

variable "authorized_cidrs" {
  type        = list(string)
  default     = []
  description = "Only used when enable_public_ip=true. Example: [\"203.0.113.10/32\"]"
}

