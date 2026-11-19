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


variable "app_name" {
  type    = string
  default = "transcript-hub"
}

variable "env" {
  type    = string
  default = "dev"
}

# Artifact Registry repo where images live
variable "ar_repo_name" {
  type    = string
  default = "apps"
}

variable "backend_service_name" {
  type    = string
  default = "transcript-backend"
}

variable "frontend_service_name" {
  type    = string
  default = "transcript-frontend"
}

variable "backend_container_port" {
  type    = number
  default = 8080
}

variable "frontend_container_port" {
  type    = number
  default = 8080
}

variable "allow_unauthenticated_backend" {
  type    = bool
  default = true
}

variable "allow_unauthenticated_frontend" {
  type    = bool
  default = true
}


variable "backend_image_name" {
  type    = string
  default = "transcript-backend"
}

variable "frontend_image_name" {
  type    = string
  default = "transcript-frontend"
}

variable "image_tag" {
  type    = string
  default = "1"
}


variable "cloudsql_instance_connection_name" {
  type        = string
  description = "PROJECT:REGION:INSTANCE"
}

variable "database_url" {
  type        = string
  description = "Backend DATABASE_URL"
}

variable "jwt_secret" {
  type      = string
  sensitive = true
}

#set CORS allowed origin to your frontend service URL
# Leave "" for first deploy, then update once frontend_url output is known.
variable "frontend_origin" {
  type        = string
  default     = ""
  description = "Frontend Cloud Run URL (e.g. https://transcript-frontend-xxxxx-uw.a.run.app) to allow in backend CORS"
}


resource "google_project_service" "cloudscheduler" {
  project            = var.project_id
  service            = "cloudscheduler.googleapis.com"
  disable_on_destroy = false
}

variable "scheduler_region" {
  type    = string
  default = "us-west2"
}

variable "scheduler_timezone" {
  type    = string
  default = "America/Los_Angeles"
}

variable "classifier_schedule" {
  type    = string
  default = "0 1 * * *" # daily 1 AM
}

variable "extractor_schedule" {
  type    = string
  default = "0 3 * * *" # daily 3 AM
}

# true only if your backend routes are /api/scheduler/...
variable "backend_has_api_prefix" {
  type    = bool
  default = false
}


variable "uc_doorway_mapping_schedule" {
  description = "Cron schedule for UC Doorway mapping job"
  type        = string
  default     = "0 5 * * *" # runs daily at 5 AM
}