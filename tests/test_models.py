import pytest
from pydantic import ValidationError

from models import AddSkillRequest, InstallResponse, SkillDetail

def test_add_skill_request_validation():
    # Valid model with url
    req = AddSkillRequest(url="https://example.com/skill.zip")
    assert req.url == "https://example.com/skill.zip"
    assert req.zip_base64 is None

    # Valid model with base64
    req = AddSkillRequest(zip_base64="UEsDBAoA...")
    assert req.url is None
    assert req.zip_base64 == "UEsDBAoA..."

def test_install_response():
    resp = InstallResponse(message="Success", installed_skills=["skill1", "skill2"])
    assert resp.message == "Success"
    assert len(resp.installed_skills) == 2
    assert "skill1" in resp.installed_skills

def test_skill_detail():
    # Create valid detail
    detail = SkillDetail(
        name="test_skill",
        description="A test skill",
        instructions="Do this",
        source_path="skills/test_skill",
        scripts=[],
        references=[]
    )
    assert detail.name == "test_skill"
    assert detail.source_path == "skills/test_skill"

    # Minimal detail
    detail2 = SkillDetail(name="min_skill", source_path="min_skill", description="desc", instructions="inst")
    assert getattr(detail2, "scripts", None) == []
