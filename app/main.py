from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as session_router

app = FastAPI(
    title="AI Technical Interview Agent",
    description=(
        "Stateful, non-generic technical interviewer grounded in candidate "
        "resume claims and GitHub public repository portfolios via OpenRouter."
    ),
    version="1.0.0",
)

# Allow CORS for development & API tools
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(session_router)


@app.get("/health", tags=["System"])
async def health_check():
    """System health check endpoint."""
    return {"status": "ok", "service": "interview-agent"}


@app.get("/", tags=["System"])
async def root():
    """Root info endpoint."""
    return {
        "service": "AI Technical Interview Agent",
        "docs_url": "/docs",
        "status": "ready",
    }
