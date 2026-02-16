provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_sql_database_instance" "student_transcripts" {
  name             = var.instance_name
  region           = var.region
  database_version = "POSTGRES_18"
  deletion_protection = true

  settings {
    tier              = var.tier
    disk_size         = var.disk_size_gb
    availability_type = "ZONAL" # change to REGIONAL for higher availability

    backup_configuration {
      enabled = true
    }

    ip_configuration {
      ipv4_enabled = var.enable_public_ip

      dynamic "authorized_networks" {
        for_each = var.enable_public_ip ? var.authorized_cidrs : []
        content {
          name  = "dev"
          value = authorized_networks.value
        }
      }
    }
  }
}

resource "google_sql_database" "db" {
  name     = var.db_name
  instance = google_sql_database_instance.student_transcripts.name
}

resource "google_sql_user" "user" {
  name     = var.db_user
  instance = google_sql_database_instance.student_transcripts.name
  password = var.db_password
}