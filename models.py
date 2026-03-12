from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SkillSummary(BaseModel):
    """Summary representation of a skill (for listing)."""

    name: str
    description: str
    scripts: List[str] = Field(default_factory=list)
    references: List[str] = Field(default_factory=list)


class SkillDetail(SkillSummary):
    """Full representation of a skill including instructions and metadata."""

    instructions: str
    source_path: str
    metadata: Optional[Dict[str, Any]] = None
    license: Optional[str] = None
    compatibility: Optional[str] = None
    allowed_tools: Optional[List[str]] = None


class AddSkillRequest(BaseModel):
    """Request body for adding a new skill."""

    # One of the following must be provided
    url: Optional[str] = Field(
        default=None,
        description="URL to download the skill .zip from.",
    )
    zip_base64: Optional[str] = Field(
        default=None,
        description="Base64-encoded .zip archive containing the skill folder.",
    )
    overwrite: bool = Field(
        default=False,
        description="If True, any existing skill with the same name will be overwritten.",
    )

    class Config:
        json_schema_extra = {
            "examples": [
                {"url": "https://example.com/my_skill.zip", "overwrite": True},
                {"zip_base64": "<base64-encoded-zip>", "overwrite": False},
            ]
        }


class UpdateSkillRequest(BaseModel):
    """Request body for updating an existing skill."""

    url: Optional[str] = Field(
        default=None,
        description="URL to download the updated skill .zip from.",
    )
    zip_base64: Optional[str] = Field(
        default=None,
        description="Base64-encoded .zip archive with the updated skill.",
    )


class MessageResponse(BaseModel):
    """Generic message response."""

    message: str


class InstallResponse(BaseModel):
    """Response returned when skills are successfully installed."""

    message: str
    installed_skills: List[str]


class ErrorResponse(BaseModel):
    """Error response."""

    detail: str
