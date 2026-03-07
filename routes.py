import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Security, UploadFile, status
from fastapi.security import APIKeyHeader

from models import (
    AddSkillRequest,
    InstallResponse,
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

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Security, UploadFile, status

@router.get(
    "/prompt_snippet",
    response_model=str,
    summary="Get system prompt snippet for agents",
)
def prompt_snippet(
    manager: Annotated[SkillManager, Depends(get_skill_manager)],
    skill_list: Optional[str] = Query(
        None,
        description="Optional comma-separated list of skill names to include in the snippet.",
    ),
) -> str:
    """Return the Agno system prompt snippet ready to be included in any agent.

    The snippet contains XML-formatted metadata for all loaded skills,
    including their names, descriptions, available scripts, and references.
    Paste this into your agent's system prompt to enable skill discovery.
    """
    skill_names = [s.strip() for s in skill_list.split(",")] if skill_list else None
    return manager.get_system_prompt_snippet(skill_names)


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
    response_model=InstallResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Install a new skill (JSON)",
)
async def add_skill(
    body: AddSkillRequest,
    manager: Annotated[SkillManager, Depends(get_skill_manager)],
) -> InstallResponse:
    """Install a new skill from a URL or base64-encoded zip archive.

    The skill name will be read from its SKILL.md.
    - Body: `url` OR `zip_base64` must be provided.
    """
    if not body.url and not body.zip_base64:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Either 'url' or 'zip_base64' must be provided.",
        )
    try:
        installed_skills = await manager.install_skill(
            url=body.url,
            zip_base64=body.zip_base64,
        )
        return InstallResponse(
            message=f"Successfully installed {len(installed_skills)} skill(s).",
            installed_skills=installed_skills,
        )
    except FileExistsError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except Exception as exc:
        logger.exception("Failed to install skill")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.post(
    "/upload",
    response_model=InstallResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Install a skill via file upload",
)
async def upload_skill(
    file: Annotated[UploadFile, File(description="Zip archive (.zip) containing the skill folder.")],
    manager: Annotated[SkillManager, Depends(get_skill_manager)],
) -> InstallResponse:
    """Install a skill by uploading a .zip file directly (multipart/form-data).

    Form fields:
    - **file**: the `.zip` archive containing the skill (must have a `SKILL.md` inside).
    """
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uploaded file must be a .zip archive.",
        )
    try:
        zip_bytes = await file.read()
        installed_skills = manager._extract_and_install_skills(zip_bytes)
        manager.reload()
        return InstallResponse(
            message=f"Successfully installed {len(installed_skills)} skill(s).",
            installed_skills=installed_skills,
        )
    except FileExistsError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except Exception as exc:
        logger.exception("Failed to upload skill")
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
