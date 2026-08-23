"""Health endpoints."""
from fastapi import APIRouter


router = APIRouter()


@router.get("")
async def health():
    return {"status": "ok"}


@router.get("/ready")
async def ready():
    return {"status": "ready"}
