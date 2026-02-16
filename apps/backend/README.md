Backend for Transcript Hub — FastAPI + PostgreSQL (Cloud SQL)

Overview
- FastAPI app providing OTP-based signup/login endpoints.
- SQL models for `profiles` and `otps` (Postgres JSONB metadata).
- OTP generation, secure hashing, expiry, verification logic.
- Pluggable notification adapters: MailerSend transactional email + a development mock sender.
- Containerized via Docker + example docker-compose.

Quickstart
1. Create a Postgres instance (Cloud SQL or local) and note the connection string (DATABASE_URL).
2. Configure `apps/backend/.env` with your database credentials and secrets.
3. Run the SQL from `apps/backend/migrations/create_tables.sql` against your Postgres instance.
4. Build and run the backend locally (from the repo root):

   docker build -t th-backend ./apps/backend
   docker run --env-file ./apps/backend/.env -p 8000:8000 th-backend

Or use the provided `docker-compose.yml` (it expects `./apps/backend/.env`).

Notes
- For Cloud SQL, prefer using the Cloud SQL Auth Proxy in production and set DATABASE_URL to a localhost socket or the proxy's address.
- The backend supports MailerSend for transactional email delivery; when `MAILERSEND_API_KEY` is not set a local mock sender is used for development.

Cloud SQL (Postgres) setup example
1. Create a Postgres instance in the Google Cloud Console (Cloud SQL) and note instance connection name.
2. Install and run the Cloud SQL Auth Proxy locally:

   ./cloud_sql_proxy -instances=PROJECT:REGION:INSTANCE=tcp:5432

3. Set `DATABASE_URL` in `apps/backend/.env` to point to the proxy (example):

   DATABASE_URL=postgresql+asyncpg://DBUSER:DBPASS@127.0.0.1:5432/transcripthub

4. Run the migration SQL to create tables (psql or other client):

   psql "postgresql://DBUSER:DBPASS@127.0.0.1:5432/transcripthub" -f apps/backend/migrations/create_tables.sql

After this the backend will be able to connect to Cloud SQL through the proxy or via configured networking/Cloud IAM.
