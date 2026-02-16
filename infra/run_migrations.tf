# One-shot migration runner using Docker and psql. Runs the SQL in infra/sql/create_tables.sql
# Usage: terraform apply -var='db_password=YOUR_PASSWORD' -target=null_resource.run_migrations

data "terraform_remote_state" "self" {
  # if using remote state, configure this; fallback to local outputs in same workspace
  backend = "local"
  config = {
    path = "terraform.tfstate"
  }
}

resource "null_resource" "run_migrations" {
  provisioner "local-exec" {
    command = <<EOT
# write the SQL to a temp file inside the container and run psql against the instance public IP
set -e
PUBLIC_IP=${data.terraform_remote_state.self.outputs.public_ip}
DB_NAME=${data.terraform_remote_state.self.outputs.db_name}
DB_USER=${data.terraform_remote_state.self.outputs.db_user}
DB_PASS="${var.db_password}"

# Run a lightweight alpine-based Postgres image so `apk` is available to install libpq, then run psql
# We mount the repo and execute psql using the public IP. Ensure the instance allows public IP connections or run this from a host that can reach the DB.
docker run --rm -v "${path.module}/sql:/sql" --entrypoint /bin/sh postgres:15-alpine -c "apk add --no-cache bash libpq && PGPASSWORD='${var.db_password}' psql -h '${data.terraform_remote_state.self.outputs.public_ip}' -U '${data.terraform_remote_state.self.outputs.db_user}' -d '${data.terraform_remote_state.self.outputs.db_name}' -f /sql/create_tables.sql"
EOT
    interpreter = ["/bin/bash", "-c"]
  }

  triggers = {
    always_run = timestamp()
  }
}
