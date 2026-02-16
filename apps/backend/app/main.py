import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers.auth import router as auth_router

# Load environment variables from .env file
load_dotenv()


app = FastAPI(title="Transcript Hub Backend")


@app.exception_handler(Exception)
async def generic_exception_handler(request, exc):
    # Return minimal JSON for unexpected server errors to help frontend parsing during development
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=500, content={"detail": str(exc)})

# configure CORS to allow Next.js frontend (read origin from env, default localhost)
FRONTEND_ORIGIN = os.environ.get('FRONTEND_ORIGIN', 'http://localhost:3000')
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register only the unified auth router
app.include_router(auth_router)


@app.get('/health')
def health():
    return {'status': 'ok', 'time': __import__('time').time()}


@app.get("/")
def root():
    return {"status": "ok", "service": "transcript-hub-backend"}
