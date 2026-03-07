import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Security, UploadFile, status
from fastapi.security import APIKeyHeader

from models import (
    AddSkillRequest,
    MessageResponse,
    SkillDetail,
    SkillSummary,
    UpdateSkillRequest,
)
from services import SkillManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dependency injection helpers
# ---------------------------------------------------------------------------

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


def get_skill_manager() -> SkillManager:
    """Dependency placeholder; overridden in main.py at startup."""
    raise RuntimeError("SkillManager not initialised")  # pragma: no cover


def verify_api_key(
    api_key: Annotated[str, Security(_api_key_header)],
    expected_key: str = Depends(lambda: _expected_api_key),
) -> str:
    """Validates the X-API-Key header against the configured secret."""
    if api_key != expected_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key.",
        )
    return api_key


# This will be set from main.py before the app starts handling requests.
_expected_api_key: str = ""


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/skills",
    tags=["Skills"],
    dependencies=[Depends(verify_api_key)],
)


@router.get(
    "",
    response_model=list[SkillSummary],
    summary="List all loaded skills",
)
def list_skills(
    manager: Annotated[SkillManager, Depends(get_skill_manager)],
) -> list[SkillSummary]:
    """Return a summary list of every currently loaded skill."""
    return manager.list_skills()


@router.get(
    "/prompt_snippet",
    response_model=str,
    summary="Get system prompt snippet for agents",
)
def prompt_snippet(
    manager: Annotated[SkillManager, Depends(get_skill_manager)],
) -> str:
    """Return the Agno system prompt snippet ready to be included in any agent.

    The snippet contains XML-formatted metadata for all loaded skills,
    including their names, descriptions, available scripts, and references.
    Paste this into your agent's system prompt to enable skill discovery.
    """
    return manager.agno.get_system_prompt_snippet()


@router.get(
    "/{unique_name}",
    response_model=SkillDetail,
    summary="Get full details for a skill",
)
def get_skill(
    unique_name: str,
    manager: Annotated[SkillManager, Depends(get_skill_manager)],
) -> SkillDetail:
    """Return full details (including instructions) for a single skill."""
    skill = manager.get_skill(unique_name)
    if skill is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill '{unique_name}' not found.",
        )
    return skill


@router.post(
    "",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Install a new skill (JSON)",
)
async def add_skill(
    unique_name: str,
    body: AddSkillRequest,
    manager: Annotated[SkillManager, Depends(get_skill_manager)],
) -> MessageResponse:
    """Install a new skill from a URL or base64-encoded zip archive.

    - `unique_name` (query param): The folder name for the skill.
    - Body: `url` OR `zip_base64` must be provided.
    """
    if not body.url and not body.zip_base64:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Either 'url' or 'zip_base64' must be provided.",
        )
    try:
        path = await manager.install_skill(
            unique_name=unique_name,
            url=body.url,
            zip_base64=body.zip_base64,
        )
        return MessageResponse(message=f"Skill '{unique_name}' installed at {path}.")
    except Exception as exc:
        logger.exception("Failed to install skill '%s'", unique_name)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.post(
    "/upload",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Install a skill via file upload",
)
async def upload_skill(
    unique_name: Annotated[str, Form(description="Unique folder name for the skill.")],
    file: Annotated[UploadFile, File(description="Zip archive (.zip) containing the skill folder.")],
    manager: Annotated[SkillManager, Depends(get_skill_manager)],
) -> MessageResponse:
    """Install a skill by uploading a .zip file directly (multipart/form-data).

    Form fields:
    - **unique_name**: the folder name to use inside SKILLS_DIR.
    - **file**: the `.zip` archive containing the skill (must have a `SKILL.md` inside).
    """
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uploaded file must be a .zip archive.",
        )
    try:
        zip_bytes = await file.read()
        path = manager._extract_zip_to_skills_dir(zip_bytes, unique_name)
        manager.reload()
        return MessageResponse(message=f"Skill '{unique_name}' installed at {path}.")
    except Exception as exc:
        logger.exception("Failed to upload skill '%s'", unique_name)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.put(
    "/{unique_name}",
    response_model=MessageResponse,
    summary="Update an existing skill",
)
async def update_skill(
    unique_name: str,
    body: UpdateSkillRequest,
    manager: Annotated[SkillManager, Depends(get_skill_manager)],
) -> MessageResponse:
    """Update an existing skill by replacing its directory with fresh content.

    Internally this is an install that overwrites the existing directory.
    """
    if not body.url and not body.zip_base64:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Either 'url' or 'zip_base64' must be provided.",
        )
    try:
        path = await manager.install_skill(
            unique_name=unique_name,
            url=body.url,
            zip_base64=body.zip_base64,
        )
        return MessageResponse(message=f"Skill '{unique_name}' updated at {path}.")
    except Exception as exc:
        logger.exception("Failed to update skill '%s'", unique_name)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.delete(
    "/{unique_name}",
    response_model=MessageResponse,
    summary="Delete a skill",
)
def delete_skill(
    unique_name: str,
    manager: Annotated[SkillManager, Depends(get_skill_manager)],
) -> MessageResponse:
    """Remove a skill from disk and unload it from the MCP server."""
    removed = manager.delete_skill(unique_name)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill '{unique_name}' not found.",
        )
    return MessageResponse(message=f"Skill '{unique_name}' deleted successfully.")
