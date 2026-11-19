output "connection_name" {
  value = google_sql_database_instance.student_transcripts.connection_name
}

output "public_ip" {
  value = try(google_sql_database_instance.student_transcripts.ip_address[0].ip_address, null)
}

output "db_name" { value = google_sql_database.db.name }
output "db_user" { value = google_sql_user.user.name }

output "cloud_run_url" {
  value = google_cloud_run_v2_service.backend.uri
}

output "artifact_registry_repo" {
  value = google_artifact_registry_repository.repo.name
}

output "backend_url" {
  value = google_cloud_run_v2_service.backend.uri
}

output "frontend_url" {
  value = google_cloud_run_v2_service.frontend.uri
}