# Transcript Hub - Complete Setup Guide

This guide will walk you through setting up the Transcript Hub application on a new laptop from a zip file.

## 📋 Table of Contents

1. [Prerequisites](#prerequisites)
2. [System Requirements](#system-requirements)
3. [Installation Steps](#installation-steps)
4. [Database Setup](#database-setup)
5. [Running the Application](#running-the-application)
6. [Troubleshooting](#troubleshooting)
7. [Verification](#verification)

---

## Prerequisites

Before you begin, ensure you have the following installed on your laptop:

### Required Software

1. **Node.js** (v18 or higher)
   - Download from: https://nodejs.org/
   - Verify installation: `node --version` and `npm --version`

2. **Python** (v3.10 or higher, tested with 3.14)
   - Download from: https://www.python.org/downloads/
   - Verify installation: `python3 --version`

3. **Google Cloud SQL Proxy**
   - Download from: https://cloud.google.com/sql/docs/mysql/sql-proxy
   - For macOS: `brew install cloud-sql-proxy`
   - For Linux: Download binary from Google Cloud
   - For Windows: Download .exe from Google Cloud
   - Verify installation: `cloud-sql-proxy --version`

4. **Git** (optional, for version control)
   - Download from: https://git-scm.com/
   - Verify installation: `git --version`

### Optional but Recommended

- **VS Code** or your preferred code editor
- **Postman** or **curl** for API testing
- **PostgreSQL Client** (psql) for database inspection

---

## System Requirements

- **Operating System**: macOS, Linux, or Windows 10/11
- **RAM**: Minimum 4GB (8GB recommended)
- **Disk Space**: At least 2GB free space
- **Internet Connection**: Required for initial setup and Cloud SQL access

---

## Installation Steps

### Step 1: Extract the Project

1. Locate the `transcript-hub.zip` file on your laptop
2. Extract it to your desired location (e.g., `~/Projects/` or `C:\Projects\`)
3. Open a terminal/command prompt and navigate to the extracted folder:

```bash
cd /path/to/transcript-hub
```

### Step 2: Install Frontend Dependencies

```bash
# Install Node.js dependencies
npm install
```

This will install all frontend dependencies listed in `package.json`. It may take 2-5 minutes depending on your internet speed.

**Expected output**: You should see a progress bar and eventually a message like "added XXX packages"

### Step 3: Install Backend Dependencies

```bash
# Navigate to backend directory
cd apps/backend

# Install Python dependencies
pip3 install -r requirements.txt

# Return to project root
cd ../..
```

**Key packages installed**:
- FastAPI 0.101.1
- Uvicorn 0.24.0
- SQLAlchemy 2.0.46
- asyncpg 0.30.0
- greenlet 3.3.1
- passlib (for password hashing)
- python-dotenv (for environment variables)

**Expected output**: You should see "Successfully installed..." messages for each package

---

## Database Setup

The application uses **Google Cloud SQL (PostgreSQL)** as its database. You need to configure the connection.

### Step 4: Configure Environment Variables

1. Navigate to the backend directory:
```bash
cd apps/backend
```

2. The `.env` file should already exist with the following configuration:

```env
# Database (Cloud SQL via proxy on localhost:5432)
DATABASE_URL=postgresql+asyncpg://admin_user:Transcript123!@127.0.0.1:5432/transcripts

# App secrets
SECRET_KEY=change-me
JWT_SECRET=change-me
JWT_ALGORITHM=HS256
JWT_EXP=3600

# OTP config
OTP_TTL_SECONDS=600
OTP_RESEND_COOLDOWN_SECONDS=30
OTP_MAX_ATTEMPTS=3

# SMTP Configuration (MailerSend)
SMTP_HOST=smtp.mailersend.net
SMTP_PORT=587
SMTP_USER=MS_bJyVnj@test-ywj2lpn739jg7oqz.mlsender.net
SMTP_PASS=mssp.UBakyi8.0p7kx4x0y2849yjr.TiFTOA5

# Frontend origin for CORS
FRONTEND_ORIGIN=http://localhost:5173
```

3. **IMPORTANT**: If you need to change any credentials, edit this file now.

### Step 5: Verify Cloud SQL Credentials

The Cloud SQL service account credentials should be located at:
```
apps/backend/cloudsql/service-account.json
```

**Verify the file exists**:
```bash
ls -la apps/backend/cloudsql/service-account.json
```

If the file is missing, you'll need to obtain it from your Google Cloud Console.


