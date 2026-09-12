"""FastAPI application skeleton for EA Bot Python services."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown hooks."""
    # Startup
    yield
    # Shutdown


app = FastAPI(
    title=settings.app_name,
    description="AI autonomous trading system — Python services",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — adjust origins in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "environment": settings.environment}


@app.get("/")
async def root():
    """Root endpoint."""
    return {"service": settings.app_name, "version": "0.1.0"}
