# FastAPI application entry point
# Run: uvicorn main:app --reload

from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

app = FastAPI(
    title="EA Bot API",
    description="Electronic Assistant Bot API Service",
    version="1.0.0"
)


class HealthResponse(BaseModel):
    status: str
    timestamp: str
    version: str


class SignalRequest(BaseModel):
    pair: str
    side: str
    price: float
    reason: Optional[str] = None
    confidence: Optional[float] = None


class SignalResponse(BaseModel):
    id: str
    status: str
    signal: dict
    created_at: str


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        status="healthy",
        timestamp=datetime.utcnow().isoformat(),
        version="1.0.0"
    )


@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "EA Bot API", "version": "1.0.0", "docs": "/docs"}


@app.post("/signals", response_model=SignalResponse)
async def create_signal(signal: SignalRequest):
    """Create a new trade signal"""
    signal_id = f"sig_{datetime.utcnow().timestamp()}"
    return SignalResponse(
        id=signal_id,
        status="received",
        signal=signal.dict(),
        created_at=datetime.utcnow().isoformat()
    )


@app.get("/signals")
async def list_signals():
    """List all trade signals"""
    return {"signals": [], "count": 0}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
