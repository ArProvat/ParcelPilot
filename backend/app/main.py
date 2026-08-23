from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, chat, decisions, health, threads
from app.config import settings
from app.schemas.auth import UserContext
from app.security.auth import get_current_user


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup lifecycle hook (initialize db, rag vectorstore, etc.)
    yield
    # Shutdown lifecycle hook


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
    lifespan=lifespan,
)

# CORS Setup
origins = settings.ALLOWED_ORIGINS if isinstance(settings.ALLOWED_ORIGINS, list) else [settings.ALLOWED_ORIGINS]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Routers
app.include_router(health.router, prefix=f"{settings.API_V1_STR}/health", tags=["Health"])
app.include_router(auth.router, prefix=f"{settings.API_V1_STR}/auth", tags=["Auth"])
app.include_router(chat.router, prefix=f"{settings.API_V1_STR}/chat", tags=["Chat & Agent"])
app.include_router(threads.router, prefix=f"{settings.API_V1_STR}/threads", tags=["Threads"])
app.include_router(decisions.router, prefix=f"{settings.API_V1_STR}/threads", tags=["Decisions & HITL"])


@app.get(f"{settings.API_V1_STR}/ready")
async def ready():
    return {"status": "ready"}


@app.get(f"{settings.API_V1_STR}/me")
async def me(user: UserContext = Depends(get_current_user)):
    return {
        "user_id": user.user_id,
        "role": user.role,
        "account_id": user.account_id,
        "permissions": sorted(user.permissions),
    }


@app.get("/")
async def root():
    return {"message": "Welcome to ParcelPilot API", "status": "running"}
