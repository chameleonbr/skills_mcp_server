import pytest
import base64
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from services import SkillManager
from agno.skills.agent_skills import Skills

@pytest.fixture
def mock_skills_loader():
    with patch("services.Skills") as mock_skills:
        mock_instance = MagicMock(spec=Skills)
        mock_skills.return_value = mock_instance
        yield mock_instance

def test_init_local_mode(tmp_path):
    manager = SkillManager(skills_dir=str(tmp_path), storage_mode="local")
    assert manager.storage_mode == "local"

@patch("boto3.client")
def test_init_s3_mode(mock_boto_client, tmp_path):
    manager = SkillManager(skills_dir=str(tmp_path), storage_mode="s3", s3_bucket="test")
    assert manager.storage_mode == "s3"
    mock_boto_client.assert_called_once()

def test_list_skills_empty(tmp_path, mock_skills_loader):
    mock_skills_loader.get_skill_names.return_value = []
    manager = SkillManager(skills_dir=str(tmp_path))
    assert manager.list_skills() == []

def test_get_skill_details_success(tmp_path, mock_skills_loader):
    mock_skill = MagicMock()
    mock_skill.name = "test_skill"
    mock_skill.description = "Test desc"
    mock_skill.instructions = "Test instructions"
    mock_skill.source_path = "path/to/test_skill"
    mock_skill.scripts = []
    mock_skill.references = []
    mock_skill.metadata = None
    mock_skill.license = None
    mock_skill.compatibility = None
    mock_skill.allowed_tools = None
    
    mock_skills_loader.get_skill.return_value = mock_skill
    
    manager = SkillManager(skills_dir=str(tmp_path))
    detail = manager.get_skill("test_skill")
    assert detail.name == "test_skill"
    assert detail.description == "Test desc"

def test_get_skill_details_not_found(tmp_path, mock_skills_loader):
    mock_skills_loader.get_skill.return_value = None
    manager = SkillManager(skills_dir=str(tmp_path))
    assert manager.get_skill("missing_skill") is None

@pytest.mark.asyncio
async def test_install_from_index_invalid_json(tmp_path):
    manager = SkillManager(skills_dir=str(tmp_path))
    
    mock_response = MagicMock()
    mock_response.json.return_value = {"not_skills": []}
    
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        with pytest.raises(ValueError) as exc:
            await manager._install_from_index("http://example.json")
        assert "must contain a 'skills' array" in str(exc.value)

def test_delete_skill(tmp_path):
    manager = SkillManager(skills_dir=str(tmp_path))
    
    # Create fake directory
    skill_dir = tmp_path / "skill_to_delete"
    skill_dir.mkdir()
    
    assert skill_dir.exists()
    assert manager.delete_skill("skill_to_delete") is True
    assert not skill_dir.exists()

def test_delete_skill_not_found(tmp_path):
    manager = SkillManager(skills_dir=str(tmp_path))
    assert manager.delete_skill("missing_skill") is False

@patch("services.Skills")
def test_get_system_prompt_snippet_filtered(mock_skills, tmp_path):
    manager = SkillManager(skills_dir=str(tmp_path))
    manager._agno_skills = MagicMock()
    
    # Mock finding a skill
    mock_skill = object()
    manager._agno_skills.get_skill.return_value = mock_skill
    
    # Provide a mock for Skills returned when recreating with loaders=[]
    filtered_mock = MagicMock()
    filtered_mock._skills = {}
    mock_skills.return_value = filtered_mock
    
    manager.get_system_prompt_snippet(["brand-guidelines"])
    
    # It should look up the skill and attach it to the new Skills dictionary
    manager._agno_skills.get_skill.assert_called_with("brand-guidelines")
    filtered_mock.get_system_prompt_snippet.assert_called_once()
    assert filtered_mock._skills["brand-guidelines"] == mock_skill
