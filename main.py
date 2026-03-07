"""Application entrypoint.

Architecture:
  - FastAPI handles the REST control plane (/skills, /health)
  - FastMCP is mounted at /mcp via its ASGI http_app (StreamableHTTP transport)
  - Lifespan wires up the SkillManager once at startup and shares it everywhere

MCP endpoint:
  Clients connect to POST /mcp (StreamableHTTP) or GET /mcp/sse (SSE) depending
  on their transport preference.
"""
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.requests import Request

import routes as skills_routes
from mcp_server import create_mcp_server
from services import SkillManager

load_dotenv()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_KEY: str = os.environ.get("API_KEY", "")
SKILLS_DIR: str = os.environ.get("SKILLS_DIR", "skills")

if not API_KEY:
    logger.warning("API_KEY is not set — the REST API will reject all requests!")

# ---------------------------------------------------------------------------
# FastMCP server
#
# We create the FastMCP instance at module load time so that @mcp.tool
# decorators register correctly. The tools use a `get_manager()` callable
# that resolves the live SkillManager from app.state at request time, so
# there is no stale-reference problem even after skill installs/reloads.
# ---------------------------------------------------------------------------
_app_ref: FastAPI | None = None  # filled in after app creation


def _get_manager() -> SkillManager:
    """Runtime resolver: return the live SkillManager from app.state."""
    assert _app_ref is not None, "FastAPI app not yet created"
    return _app_ref.state.skill_manager


mcp = create_mcp_server(get_manager=_get_manager)


# ---------------------------------------------------------------------------
# MCP Auth Middleware
#
# The FastMCP ASGI sub-app is mounted outside FastAPI's dependency injection,
# so API key validation must be enforced via middleware instead.
# ---------------------------------------------------------------------------
class MCPAuthMiddleware(BaseHTTPMiddleware):
    """Protect the /mcp endpoint with the same X-API-Key used by the REST API."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path.startswith("/mcp"):
            key = request.headers.get("X-API-Key", "")
            if not key:
                return Response(
                    content='{"detail": "X-API-Key header missing."}',
                    status_code=401,
                    media_type="application/json",
                )
            if key != API_KEY:
                return Response(
                    content='{"detail": "Invalid API key."}',
                    status_code=403,
                    media_type="application/json",
                )
        return await call_next(request)

# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialise shared resources on startup; clean up on shutdown."""
    logger.info("Starting up Skills MCP Server …")

    skill_manager = SkillManager(skills_dir=SKILLS_DIR)
    app.state.skill_manager = skill_manager

    # Wire API key and SkillManager into REST route dependencies
    skills_routes._expected_api_key = API_KEY
    app.dependency_overrides[skills_routes.get_skill_manager] = lambda: skill_manager

    logger.info(
        "Loaded %d skill(s) from '%s'",
        len(skill_manager.list_skills()),
        SKILLS_DIR,
    )

    yield  # ← server handles requests here

    logger.info("Shutting down.")


app = FastAPI(
    title="Skills MCP Server",
    description=(
        "A centralized MCP server for managing and executing Agno agent skills.\n\n"
        "- **REST control plane** (`/skills`): install, update, list, delete skills.\n"
        "- **MCP endpoint** (`/mcp`): StreamableHTTP transport for MCP clients."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# Set the app reference so `_get_manager` can access app.state at request time
_app_ref = app

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
# MCPAuthMiddleware is added AFTER CORSMiddleware so that it runs FIRST
# (Starlette applies middleware in reverse registration order).
app.add_middleware(MCPAuthMiddleware)


# ---------------------------------------------------------------------------
# REST routes (/skills)
# ---------------------------------------------------------------------------
app.include_router(skills_routes.router)

# ---------------------------------------------------------------------------
# FastMCP mounted at /mcp  (StreamableHTTP transport)
#
# mcp.http_app() returns a Starlette ASGI sub-application with its own
# internal lifespan. FastAPI's app.mount() integrates it so that:
#   POST /mcp     → MCP initialize / tool calls (StreamableHTTP)
#   GET  /mcp/sse → Server-Sent Events stream (SSE transport)
# ---------------------------------------------------------------------------
app.mount("/mcp", mcp.http_app(path="/mcp"))

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health", tags=["Health"], summary="Health check")
def health() -> JSONResponse:
    """Returns 200 OK with the number of currently loaded skills."""
    manager: SkillManager = app.state.skill_manager
    return JSONResponse(
        {
            "status": "ok",
            "skills_loaded": len(manager.list_skills()),
        }
    )
