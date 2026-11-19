locals {
  backend_image_ref  = "${var.region}-docker.pkg.dev/${var.project_id}/${var.ar_repo_name}/${var.backend_image_name}:${var.image_tag}"
  frontend_image_ref = "${var.region}-docker.pkg.dev/${var.project_id}/${var.ar_repo_name}/${var.frontend_image_name}:${var.image_tag}"
}

resource "google_project_service" "run" {
  project            = var.project_id
  service            = "run.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "artifactregistry" {
  project            = var.project_id
  service            = "artifactregistry.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "sqladmin" {
  project            = var.project_id
  service            = "sqladmin.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "iam" {
  project            = var.project_id
  service            = "iam.googleapis.com"
  disable_on_destroy = false
}

# # Optional but helpful if you use Cloud Build to build/push images
# resource "google_project_service" "cloudbuild" {
#   project            = var.project_id
#   service            = "cloudbuild.googleapis.com"
#   disable_on_destroy = false
# }


# Artifact Registry repo
resource "google_artifact_registry_repository" "repo" {
  depends_on    = [google_project_service.artifactregistry]
  location      = var.region
  repository_id = var.ar_repo_name
  format        = "DOCKER"
}


resource "google_service_account" "backend_sa" {
  depends_on   = [google_project_service.iam]
  account_id   = "${var.backend_service_name}-sa"
  display_name = "Runtime SA for ${var.backend_service_name}"
}

resource "google_service_account" "frontend_sa" {
  depends_on   = [google_project_service.iam]
  account_id   = "${var.frontend_service_name}-sa"
  display_name = "Runtime SA for ${var.frontend_service_name}"
}

# Allow both SAs to pull from Artifact Registry
resource "google_artifact_registry_repository_iam_member" "backend_sa_reader" {
  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.repo.name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.backend_sa.email}"
}

resource "google_artifact_registry_repository_iam_member" "frontend_sa_reader" {
  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.repo.name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.frontend_sa.email}"
}

# Backend SA can connect to Cloud SQL
resource "google_project_iam_member" "backend_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.backend_sa.email}"
}


# Cloud Run: BACKEND
resource "google_cloud_run_v2_service" "backend" {
  depends_on = [
    google_project_service.run,
    google_artifact_registry_repository.repo,
    google_artifact_registry_repository_iam_member.backend_sa_reader,
    google_project_iam_member.backend_cloudsql_client,
  ]

  name     = var.backend_service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.backend_sa.email

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [var.cloudsql_instance_connection_name]
      }
    }

    containers {
      image = local.backend_image_ref

      ports {
        container_port = var.backend_container_port
      }

      env {
        name  = "DATABASE_URL"
        value = var.database_url
      }

      env {
        name  = "JWT_SECRET"
        value = var.jwt_secret
      }

      dynamic "env" {
        for_each = var.frontend_origin != "" ? [1] : []
        content {
          name  = "FRONTEND_ORIGIN"
          value = var.frontend_origin
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "backend_public_invoker" {
  count    = var.allow_unauthenticated_backend ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.backend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}


resource "google_cloud_run_v2_service" "frontend" {

  name     = var.frontend_service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.frontend_sa.email

    containers {
      image = local.frontend_image_ref

      ports {
        container_port = var.frontend_container_port
      }

      env {
        name  = "BACKEND_URL"
        value = google_cloud_run_v2_service.backend.uri
      }
    }
  }
}


resource "google_cloud_run_v2_service_iam_member" "frontend_public_invoker" {
  count    = var.allow_unauthenticated_frontend ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.frontend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

