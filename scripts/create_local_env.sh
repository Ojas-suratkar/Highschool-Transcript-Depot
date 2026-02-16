#!/usr/bin/env zsh
set -euo pipefail

ENVFILE="apps/backend/.env"
BACKUP="${ENVFILE}.bak"

echo "This script will create ${ENVFILE} (it is gitignored)."
if [ -f "${ENVFILE}" ]; then
  echo "Existing ${ENVFILE} found — backing up to ${BACKUP}"
  cp "${ENVFILE}" "${BACKUP}"
fi

read -r -p "Delivery method (mailersend/smtp/mock) [mailersend]: " DELIVERY_METHOD
DELIVERY_METHOD=${DELIVERY_METHOD:-mailersend}

DEFAULT_DB="postgresql+asyncpg://transcript_user:transcript_pass@127.0.0.1:5432/transcripts_db"
read -r -p "DATABASE_URL [${DEFAULT_DB}]: " DATABASE_URL
DATABASE_URL=${DATABASE_URL:-${DEFAULT_DB}}

read -r -p "JWT_SECRET [local-change-me]: " JWT_SECRET
JWT_SECRET=${JWT_SECRET:-local-change-me}

SENDER_EMAIL_DEFAULT="no-reply@example.com"
read -r -p "SENDER_EMAIL [${SENDER_EMAIL_DEFAULT}]: " SENDER_EMAIL
SENDER_EMAIL=${SENDER_EMAIL:-${SENDER_EMAIL_DEFAULT}}
read -r -p "SENDER_NAME [Transcript Hub]: " SENDER_NAME
SENDER_NAME=${SENDER_NAME:-"Transcript Hub"}

MAILERSEND_API_KEY=""
MAILERSEND_DOMAIN=""
MAILERSEND_SENDER_EMAIL=""
MAILERSEND_SENDER_NAME=""

SMTP_HOST=""
SMTP_PORT=""
SMTP_USER=""
SMTP_PASS=""
SMTP_USE_TLS="true"

if [ "${DELIVERY_METHOD}" = "mailersend" ]; then
  echo "--- MailerSend configuration ---"
  read -r -p "MAILERSEND_API_KEY: " MAILERSEND_API_KEY
  read -r -p "MAILERSEND_DOMAIN (optional): " MAILERSEND_DOMAIN
  read -r -p "MAILERSEND_SENDER_EMAIL [${SENDER_EMAIL}]: " MAILERSEND_SENDER_EMAIL
  MAILERSEND_SENDER_EMAIL=${MAILERSEND_SENDER_EMAIL:-${SENDER_EMAIL}}
  read -r -p "MAILERSEND_SENDER_NAME [${SENDER_NAME}]: " MAILERSEND_SENDER_NAME
  MAILERSEND_SENDER_NAME=${MAILERSEND_SENDER_NAME:-${SENDER_NAME}}
elif [ "${DELIVERY_METHOD}" = "smtp" ]; then
  echo "--- SMTP configuration ---"
  read -r -p "SMTP_HOST [smtp.example.com]: " SMTP_HOST
  SMTP_HOST=${SMTP_HOST:-smtp.example.com}
  read -r -p "SMTP_PORT [587]: " SMTP_PORT
  SMTP_PORT=${SMTP_PORT:-587}
  read -r -p "SMTP_USER: " SMTP_USER
  read -r -s -p "SMTP_PASS: " SMTP_PASS
  echo
  read -r -p "Use TLS? (y/n) [y]: " TLS_ANS
  TLS_ANS=${TLS_ANS:-y}
  if [[ "${TLS_ANS}" =~ ^([yY]|yes)$ ]]; then
    SMTP_USE_TLS=true
  else
    SMTP_USE_TLS=false
  fi
else
  echo "Using mock delivery; no provider credentials will be written."
fi

cat > "${ENVFILE}" <<EOF
DATABASE_URL=${DATABASE_URL}
JWT_SECRET=${JWT_SECRET}
JWT_ALGORITHM=HS256
JWT_EXP=3600
JWT_ISS=transcript-hub-local
FRONTEND_ORIGIN=http://localhost:5173

DELIVERY_MODE=${DELIVERY_METHOD}

SMTP_HOST=${SMTP_HOST}
SMTP_PORT=${SMTP_PORT}
SMTP_USER=${SMTP_USER}
SMTP_PASS=${SMTP_PASS}
SMTP_USE_TLS=${SMTP_USE_TLS}

MAILERSEND_API_KEY=${MAILERSEND_API_KEY}
MAILERSEND_DOMAIN=${MAILERSEND_DOMAIN}
MAILERSEND_SENDER_EMAIL=${MAILERSEND_SENDER_EMAIL}
MAILERSEND_SENDER_NAME=${MAILERSEND_SENDER_NAME}

SENDER_EMAIL=${SENDER_EMAIL}
SENDER_NAME="${SENDER_NAME}"

DEV_ADMIN_KEY=dev-admin-key
SENDER_EMAIL=${SENDER_EMAIL}

EOF

chmod 600 "${ENVFILE}"
echo "Wrote ${ENVFILE} (permissions 600)."
echo "Note: ${ENVFILE} is listed in .gitignore — it will not be committed."
echo "To run the backend now: activate your venv and run:\n  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --app-dir apps/backend"
