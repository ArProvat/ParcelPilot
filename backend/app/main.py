from contextlib import asynccontextmanager
import logging
import time
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, chat, decisions, documents, health, threads
from app.config import settings
from app.api.health import readiness_status
from app.schemas.auth import UserContext
from app.security.auth import get_current_user


logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
logger = logging.getLogger("parcelpilot.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup: build the LangGraph agent stack once and store in app.state."""
    from app.agent import AgentEventTranslator, close_checkpointer, create_chat_model, create_checkpointer, create_parcelpilot_agent
    from app.db.session import AsyncSessionLocal
    from app.services.agent_stream import AgentStreamService
    from app.tools import create_agent_tools

    logger.info("parcelpilot_startup_begin")

    # Build components once — reused for the lifetime of the process.
    model = create_chat_model()
    checkpointer = await create_checkpointer()
    tools = create_agent_tools(session_factory=AsyncSessionLocal)
    agent = create_parcelpilot_agent(model=model, tools=tools, checkpointer=checkpointer)
    translator = AgentEventTranslator()

    app.state.agent_stream_service = AgentStreamService(
        agent=agent,
        session_factory=AsyncSessionLocal,
        event_translator=translator,
    )

    logger.info("parcelpilot_startup_complete")
    yield

    # Shutdown: close the checkpointer connection pool cleanly.
    await close_checkpointer(checkpointer)
    logger.info("parcelpilot_shutdown_complete")


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


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or f"req_{uuid4().hex[:12]}"
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.exception(
            "request_failed",
            extra={
                "parcelpilot": {
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": duration_ms,
                }
            },
        )
        raise

    duration_ms = int((time.perf_counter() - started) * 1000)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request_completed",
        extra={
            "parcelpilot": {
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            }
        },
    )
    return response

# Include API Routers
app.include_router(health.router, prefix=f"{settings.API_V1_STR}/health", tags=["Health"])
app.include_router(auth.router, prefix=f"{settings.API_V1_STR}/auth", tags=["Auth"])
app.include_router(chat.router, prefix=f"{settings.API_V1_STR}/chat", tags=["Chat & Agent"])
app.include_router(threads.router, prefix=f"{settings.API_V1_STR}/threads", tags=["Threads"])
app.include_router(decisions.router, prefix=f"{settings.API_V1_STR}/threads", tags=["Decisions & HITL"])
app.include_router(documents.router, prefix=f"{settings.API_V1_STR}/documents", tags=["Knowledge Base"])


@app.get(f"{settings.API_V1_STR}/ready")
async def ready():
    return await readiness_status()


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
