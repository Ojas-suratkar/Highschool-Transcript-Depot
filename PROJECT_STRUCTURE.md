# Project Structure

## Directory Tree

```
transcript-hub/
│
├── 📁 apps/                          # Application code
│   │
│   ├── 📁 frontend/                  # React + Vite frontend
│   │   ├── 📁 public/               # Static assets (index.html, favicon, etc.)
│   │   ├── 📁 src/
│   │   │   ├── 📁 components/       # Reusable UI components
│   │   │   │   ├── dialogs/        # Modal dialogs
│   │   │   │   ├── layout/         # Layout components (Sidebar, Header, etc.)
│   │   │   │   ├── shared/         # Shared components (Logo, etc.)
│   │   │   │   └── ui/             # Base UI components (Button, Input, etc.)
│   │   │   ├── 📁 contexts/         # React context providers
│   │   │   ├── 📁 hooks/            # Custom React hooks
│   │   │   ├── 📁 lib/              # Utility libraries
│   │   │   ├── 📁 pages/            # Page components
│   │   │   │   ├── Landing.tsx     # Landing page
│   │   │   │   ├── Login.tsx       # Login page
│   │   │   │   ├── Signup.tsx      # Signup page
│   │   │   │   ├── Dashboard.tsx   # Main dashboard
│   │   │   │   └── [50+ pages]     # Other application pages
│   │   │   ├── 📁 styles/           # Global styles
│   │   │   ├── 📁 types/            # TypeScript type definitions
│   │   │   ├── App.tsx             # Root component
│   │   │   └── main.tsx            # Entry point
│   │   └── package.json            # Frontend dependencies
│   │
│   └── 📁 backend/                   # FastAPI + PostgreSQL backend
│       ├── 📁 alembic/              # Database migrations (Alembic)
│       │   └── versions/           # Migration versions
│       ├── 📁 app/
│       │   ├── 📁 core/             # Core configuration
│       │   ├── 📁 delivery/         # Email delivery adapters
│       │   ├── 📁 notifications/    # Notification services
│       │   ├── 📁 routers/          # API route handlers
│       │   │   └── auth.py         # Authentication endpoints
│       │   ├── 📁 services/         # Business logic
│       │   │   └── auth_service.py # Auth service
│       │   ├── 📁 utils/            # Utility functions
│       │   ├── db.py               # Database configuration
│       │   ├── main.py             # FastAPI application
│       │   ├── models.py           # SQLAlchemy models
│       │   └── schemas.py          # Pydantic schemas
│       ├── 📁 cloudsql/             # Cloud SQL credentials
│       │   └── service-account.json
│       ├── 📁 migrations/           # SQL migration scripts
│       ├── .env                    # Environment variables (gitignored)
│       └── requirements.txt        # Python dependencies
│
├── 📁 infra/                         # Infrastructure as Code
│   ├── 📁 sql/                      # SQL initialization scripts
│   ├── main.tf                     # Main Terraform configuration
│   ├── outputs.tf                  # Terraform outputs
│   ├── variables.tf                # Terraform variables
│   ├── terraform.tfvars            # Terraform variable values
│   └── terraform.tfstate           # Terraform state (gitignored)
│
├── 📁 scripts/                       # Utility scripts
│   ├── create_local_env.sh         # Environment setup script
│   └── start-frontend.mjs          # Frontend start script
│
├── 📁 node_modules/                  # Frontend dependencies (gitignored)
│
├── 📄 .gitignore                     # Git ignore rules
├── 📄 docker-compose.yml             # Docker Compose configuration
├── 📄 package.json                   # Root package.json (frontend)
├── 📄 package-lock.json              # NPM lock file
├── 📄 postcss.config.mjs             # PostCSS configuration
├── 📄 README.md                      # Project documentation
├── 📄 tsconfig.json                  # TypeScript configuration
├── 📄 tsconfig.app.json              # TypeScript app configuration
└── 📄 vite.config.ts                 # Vite configuration

```

## Key Files

### Root Configuration

| File | Purpose |
|------|---------|
| `vite.config.ts` | Vite build configuration, sets root to `apps/frontend` |
| `package.json` | Frontend dependencies and scripts |
| `tsconfig.json` | TypeScript compiler configuration |
| `.gitignore` | Git ignore patterns |
| `docker-compose.yml` | Docker services configuration |

### Frontend (`apps/frontend/`)

| File/Directory | Purpose |
|----------------|---------|
| `src/main.tsx` | Application entry point |
| `src/App.tsx` | Root React component with routing |
| `src/pages/` | Page components (50+ pages) |
| `src/components/` | Reusable UI components |
| `src/contexts/` | React context providers |
| `src/hooks/` | Custom React hooks |
| `public/index.html` | HTML template |

### Backend (`apps/backend/`)

| File/Directory | Purpose |
|----------------|---------|
| `app/main.py` | FastAPI application entry point |
| `app/db.py` | Database connection and session management |
| `app/models.py` | SQLAlchemy ORM models |
| `app/schemas.py` | Pydantic request/response schemas |
| `app/routers/` | API endpoint handlers |
| `app/services/` | Business logic layer |
| `.env` | Environment variables (DATABASE_URL, SMTP, etc.) |
| `requirements.txt` | Python dependencies |

### Infrastructure (`infra/`)

| File | Purpose |
|------|---------|
| `main.tf` | Main Terraform configuration (Cloud SQL, networking) |
| `outputs.tf` | Terraform outputs (connection strings, IPs) |
| `terraform.tfstate` | Current infrastructure state |

## Clean Structure Benefits

✅ **Clear Separation:** Frontend and backend are cleanly separated in `apps/`  
✅ **No Duplication:** Removed duplicate `src/` and `backend/` directories  
✅ **Minimal Root:** Only essential config files at root level  
✅ **Easy Navigation:** Logical folder hierarchy  
✅ **Scalable:** Easy to add new apps or services  
✅ **Standard Monorepo:** Follows industry best practices  

## Running the Application

See [README.md](README.md) for detailed setup and running instructions.
