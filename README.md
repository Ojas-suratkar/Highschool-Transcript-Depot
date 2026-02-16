# Transcript Hub

A full-stack web application for managing high school transcripts with automated extraction, verification, and admissions workflows.

## 🏗️ Project Structure

```
transcript-hub/
├── apps/
│   ├── frontend/          # React + Vite frontend application
│   │   ├── public/        # Static assets
│   │   └── src/
│   │       ├── components/  # Reusable UI components
│   │       ├── contexts/    # React contexts
│   │       ├── hooks/       # Custom React hooks
│   │       ├── lib/         # Utility libraries
│   │       ├── pages/       # Page components
│   │       ├── styles/      # Global styles
│   │       └── types/       # TypeScript type definitions
│   │
│   └── backend/           # FastAPI + PostgreSQL backend
│       ├── alembic/       # Database migrations
│       ├── app/
│       │   ├── core/      # Core configuration
│       │   ├── delivery/  # Email delivery adapters
│       │   ├── routers/   # API route handlers
│       │   ├── services/  # Business logic
│       │   └── utils/     # Utility functions
│       ├── cloudsql/      # Cloud SQL credentials
│       └── migrations/    # SQL migration scripts
│
├── infra/                 # Terraform infrastructure as code
│   └── sql/              # SQL initialization scripts
│
├── scripts/              # Utility scripts
│
└── [config files]        # Root-level configuration files
```

## 🚀 Quick Start

### Prerequisites

- **Node.js** 18+ and npm
- **Python** 3.14+
- **Cloud SQL Proxy** (for database access)
- **PostgreSQL** (Cloud SQL instance)

### 1. Install Dependencies

```bash
# Install frontend dependencies
npm install

# Install backend dependencies
cd apps/backend
pip3 install -r requirements.txt
cd ../..
```

### 2. Configure Environment

```bash
# Backend environment variables are in apps/backend/.env
# Database, SMTP, and JWT secrets are already configured
```

### 3. Start Cloud SQL Proxy

```bash
cloud-sql-proxy --credentials-file=apps/backend/cloudsql/service-account.json \
  doc-ai-transcript:us-west2:student-transcripts
```

### 4. Start Development Servers

**Terminal 1 - Backend:**
```bash
cd apps/backend
python3 -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Terminal 2 - Frontend:**
```bash
npm run dev
```

**Terminal 3 - Cloud SQL Proxy:**
```bash
# Already running from step 3
```

### 5. Access the Application

- **Frontend:** http://localhost:5173
- **Backend API:** http://localhost:8000
- **API Health Check:** http://localhost:8000/health

## 🛠️ Technology Stack

### Frontend
- **Framework:** React 18.3.1 with TypeScript
- **Build Tool:** Vite 6.3.5
- **Routing:** React Router v7.12.0
- **State Management:** TanStack Query
- **UI Components:** Radix UI, Material-UI 7.3.5
- **Styling:** Tailwind CSS 4.1.12
- **Icons:** Lucide React

### Backend
- **Framework:** FastAPI 0.101.1
- **Server:** Uvicorn 0.24.0
- **Database:** PostgreSQL (Cloud SQL)
- **ORM:** SQLAlchemy 2.0.46 (async)
- **Database Driver:** asyncpg 0.30.0
- **Authentication:** JWT tokens with OTP verification
- **Email:** SMTP via MailerSend

### Infrastructure
- **Cloud Provider:** Google Cloud Platform
- **Database:** Cloud SQL (PostgreSQL)
- **IaC:** Terraform
- **Proxy:** Cloud SQL Proxy for secure connections

## 📝 Key Features

- **OTP-based Authentication:** Secure email-based signup and login
- **Transcript Management:** Upload, extract, and verify high school transcripts
- **Automated Extraction:** Parse courses, grades, and GPA with confidence scores
- **Manual Review:** Flagged cases surfaced for reviewers to correct and approve
- **Admissions Workflows:** Program requirements, criteria, and decision templates
- **Cloud Integration:** Connect Drive or S3 folders for continuous intake
- **Role-based Access:** Institution-ready with role controls and audit trails

## 🔧 Development

### Frontend Development

The frontend uses Vite with hot module replacement. Changes to React components will automatically reload in the browser.

**Key directories:**
- `apps/frontend/src/pages/` - Page components (Landing, Login, Signup, Dashboard, etc.)
- `apps/frontend/src/components/` - Reusable UI components
- `apps/frontend/src/contexts/` - React context providers

### Backend Development

The backend uses FastAPI with auto-reload enabled. Changes to Python files will automatically restart the server.

**Key directories:**
- `apps/backend/app/routers/` - API endpoints
- `apps/backend/app/services/` - Business logic
- `apps/backend/app/models.py` - Database models

### Database

The application uses Cloud SQL (PostgreSQL) accessed via Cloud SQL Proxy.

**Connection details:**
- Instance: `doc-ai-transcript:us-west2:student-transcripts`
- Local proxy: `127.0.0.1:5432`
- Database: `transcripts`

## 📚 API Documentation

Once the backend is running, visit:
- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

## 🔐 Environment Variables

Backend environment variables are configured in `apps/backend/.env`:

- `DATABASE_URL` - PostgreSQL connection string (via Cloud SQL Proxy)
- `SECRET_KEY` - Application secret key
- `JWT_SECRET` - JWT token secret
- `SMTP_*` - Email delivery configuration
- `FRONTEND_ORIGIN` - CORS allowed origin

## 📦 Build for Production

```bash
# Build frontend
npm run build

# Output will be in apps/frontend/dist/
```

## 🤝 Contributing

This is a private project. For questions or issues, contact the development team.

## 📄 License

Proprietary - All rights reserved
  