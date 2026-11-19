locals {
  backend_api_prefix = var.backend_has_api_prefix ? "/api" : ""
  classifier_url = "${google_cloud_run_v2_service.backend.uri}${local.backend_api_prefix}/api/pipeline/run-semester"
  extractor_url  = "${google_cloud_run_v2_service.backend.uri}${local.backend_api_prefix}/api/cloud-folder-locations/extract-all"
  uc_doorway_mapping_url = "${google_cloud_run_v2_service.backend.uri}${local.backend_api_prefix}/api/uc-doorway-course-mapping/run"
}

resource "google_cloud_scheduler_job" "classifier_daily" {
  depends_on = [
    google_project_service.cloudscheduler,
    google_cloud_run_v2_service.backend,
  ]

  name        = "classifier-daily"
  description = "Run classifier pipeline daily"
  region      = var.scheduler_region

  schedule  = var.classifier_schedule
  time_zone = var.scheduler_timezone

  http_target {
    http_method = "POST"
    uri         = local.classifier_url

    headers = {
      "Content-Type" = "application/json"
    }

    body = base64encode(jsonencode({
      trigger = "cloud-scheduler"
      job     = "classifier"
    }))
  }

  retry_config {
    retry_count = 3
  }
}


resource "google_cloud_scheduler_job" "extractor_daily" {
  depends_on = [
    google_project_service.cloudscheduler,
    google_cloud_run_v2_service.backend,
  ]

  name        = "extractor-daily"
  description = "Run extractor pipeline daily"
  region      = var.scheduler_region

  schedule  = var.extractor_schedule
  time_zone = var.scheduler_timezone

  http_target {
    http_method = "POST"
    uri         = local.extractor_url

    headers = {
      "Content-Type" = "application/json"
    }

    body = base64encode(jsonencode({
      trigger = "cloud-scheduler"
      job     = "extractor"
    }))
  }

  retry_config {
    retry_count = 3
  }
}


resource "google_cloud_scheduler_job" "uc_doorway_mapping_daily" {
  depends_on = [
    google_project_service.cloudscheduler,
    google_cloud_run_v2_service.backend,
  ]

  name        = "uc-doorway-mapping-daily"
  description = "Run UC Doorway course mapping job daily"
  region      = var.scheduler_region

  schedule  = var.uc_doorway_mapping_schedule
  time_zone = var.scheduler_timezone

  http_target {
    http_method = "POST"
    uri         = local.uc_doorway_mapping_url

    headers = {
      "Content-Type" = "application/json"
    }

    body = base64encode(jsonencode({
      trigger = "cloud-scheduler"
      job     = "uc-doorway-mapping"
    }))
  }

  retry_config {
    retry_count = 3
  }
}