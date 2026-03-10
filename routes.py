import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Security, UploadFile, status
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

ENFORCEMENT_PROMPT = """
<skills_usage_enforcement>

## Critical Rule: Mandatory Use of Skills

You have access to a system of specialized skills. Before responding to any question that falls within the domain of an available skill, you MUST follow the workflow below — no exceptions.

### Mandatory Workflow

1. **Identify** whether the user's request matches the domain of any skill listed in `<skills_system>`
2. **Load** the skill instructions via `get_skill_instructions(skill_name)` BEFORE formulating any response
3. **Consult references** with `get_skill_reference(skill_name, reference_path)` when available and relevant
4. **Execute scripts** with `get_skill_script(skill_name, script_path)` only when `<scripts>` lists actual files

### Absolute Prohibitions

- ❌ NEVER respond based solely on your general knowledge when a relevant skill is available
- ❌ NEVER call the skill name as if it were a function (e.g., `example-skill(...)`)
- ❌ NEVER skip `get_skill_instructions` and jump directly to `get_skill_reference` or `get_skill_script`
- ❌ NEVER use `get_skill_script` on skills that declare `<scripts>none</scripts>`

### Activation Criteria

If **any part** of the user's request touches the domain of an available skill, that skill must be loaded. When in doubt, load the skill — it is better to load unnecessarily than to ignore it.

### Response Format After Loading a Skill

Only after executing `get_skill_instructions` are you authorized to compose your response, strictly following the instructions returned by the skill.

</skills_usage_enforcement>
"""

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
    prompt_enforcement: Optional[bool] = Query(
        True,
        description="Optional prompt enforcement string to include in the snippet. If True, the snippet will include a prompt enforcement string.",
    ),
) -> str:
    """Return the Agno system prompt snippet ready to be included in any agent.

    The snippet contains XML-formatted metadata for all loaded skills,
    including their names, descriptions, available scripts, and references.
    Paste this into your agent's system prompt to enable skill discovery.
    """
    skill_names = [s.strip() for s in skill_list.split(",")] if skill_list else None
    snippet = manager.get_system_prompt_snippet(skill_names)
    if prompt_enforcement:
        return ENFORCEMENT_PROMPT + "\n\n" + snippet
    return snippet


@router.post(
    "/prompt_snippet",
    summary="Inject system prompt snippet into a request body",
)
def prompt_snippet_post(
    manager: Annotated[SkillManager, Depends(get_skill_manager)],
    request_body: dict = Body(...),
    skill_list: Optional[str] = Query(
        None,
        description="Optional comma-separated list of skill names to include in the snippet.",
    ),
    prompt_enforcement: Optional[bool] = Query(
        True,
        description="Optional prompt enforcement string to include in the snippet. If True, the snippet will include a prompt enforcement string.",
    ),
) -> dict:
    """Return the received body with an injected 'prompt' string containing the Agno skills snippet.

    This is useful for low-code tools (like n8n) to build an agent payload in one step.
    Everything passed in the JSON body is returned as-is, with 'prompt' appended or overwritten.
    """
    skill_names = [s.strip() for s in skill_list.split(",")] if skill_list else None
    snippet = manager.get_system_prompt_snippet(skill_names)
    if prompt_enforcement:
        snippet = ENFORCEMENT_PROMPT + "\n\n" + snippet
    
    response_body = request_body.copy()
    response_body["prompt"] = snippet
    return response_body


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
            overwrite=body.overwrite,
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
    file: Annotated[UploadFile, File(description="Archive (.zip or .skill) containing the skill folder.")],
    manager: Annotated[SkillManager, Depends(get_skill_manager)],
    overwrite: bool = Form(False, description="If True, any existing skill with the same name will be overwritten."),
) -> InstallResponse:
    """Install a skill by uploading an archive file directly (multipart/form-data).

    Form fields:
    - **file**: the `.zip` or `.skill` archive containing the skill (must have a `SKILL.md` inside).
    """
    if not file.filename or not (file.filename.endswith(".zip") or file.filename.endswith(".skill")):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uploaded file must be a .zip or .skill archive.",
        )
    try:
        zip_bytes = await file.read()
        installed_skills = manager._extract_and_install_skills(zip_bytes, overwrite=overwrite)
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


@router.delete(
    "",
    response_model=MessageResponse,
    summary="Delete all skills",
)
def delete_all_skills(
    manager: Annotated[SkillManager, Depends(get_skill_manager)],
) -> MessageResponse:
    """Remove all skills from disk and unload them from the MCP server."""
    count = manager.delete_all_skills()
    return MessageResponse(message=f"Successfully deleted {count} skill(s).")
