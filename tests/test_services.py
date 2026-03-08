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


def test_validate_safe_name(tmp_path):
    manager = SkillManager(skills_dir=str(tmp_path))
    # Should not raise
    manager._validate_safe_name("valid-name_123")
    
    with pytest.raises(ValueError, match="Invalid skill_name format"):
        manager._validate_safe_name("invalid name!", "skill_name")

    with pytest.raises(ValueError, match="Invalid name format"):
        manager._validate_safe_name("../traversal")


def test_validate_safe_path(tmp_path):
    manager = SkillManager(skills_dir=str(tmp_path))
    # Should not raise
    manager._validate_safe_path("valid/path/file.py")
    
    with pytest.raises(ValueError, match="Directory traversal and absolute paths are not allowed."):
        manager._validate_safe_path("../secret.txt")

    with pytest.raises(ValueError, match="Directory traversal and absolute paths are not allowed."):
        manager._validate_safe_path("/etc/passwd")


def test_mcp_get_script_security_validations(tmp_path):
    manager = SkillManager(skills_dir=str(tmp_path))
    manager._agno_skills = MagicMock()
    manager._agno_skills._get_skill_script.return_value = "script output"

    # Valid call
    assert manager.mcp_get_script("safe-skill", "safe_script.py") == "script output"
    manager._agno_skills._get_skill_script.assert_called_with("safe-skill", "safe_script.py", execute=False, args=None)

    # Invalid names/paths
    with pytest.raises(ValueError):
        manager.mcp_get_script("bad name", "safe_script.py")
    
    with pytest.raises(ValueError):
        manager.mcp_get_script("safe-skill", "/etc/passwd")


def test_mcp_get_script_execute_disabled(tmp_path):
    manager = SkillManager(skills_dir=str(tmp_path), allow_run_scripts=False)
    manager._agno_skills = MagicMock()

    # Reading script is allowed
    manager.mcp_get_script("safe-skill", "safe_script.py", execute=False)
    manager._agno_skills._get_skill_script.assert_called_with("safe-skill", "safe_script.py", execute=False, args=None)

    # Executing script is blocked
    with pytest.raises(ValueError, match="Script execution is disabled"):
        manager.mcp_get_script("safe-skill", "safe_script.py", execute=True)


def test_mcp_get_script_execute_enabled_with_shell_injection(tmp_path):
    manager = SkillManager(skills_dir=str(tmp_path), allow_run_scripts=True)
    manager._agno_skills = MagicMock()
    manager._agno_skills._get_skill_script.return_value = "script output"

    # Shell injection in arguments is still blocked
    with pytest.raises(ValueError, match="forbidden shell characters"):
        manager.mcp_get_script("safe-skill", "safe_script.py", execute=True, args=["arg1", "; ls"])

    with pytest.raises(ValueError, match="forbidden shell characters"):
        manager.mcp_get_script("safe-skill", "safe_script.py", execute=True, args=["arg1", "&& rm -rf /"])


def test_setup_skill_venv_creates_venv(tmp_path):
    manager = SkillManager(skills_dir=str(tmp_path))
    skill_dir = tmp_path / "venv_skill"
    skill_dir.mkdir()
    (skill_dir / "requirements.txt").write_text("requests==2.28.2")

    with patch("subprocess.run") as mock_run:
        manager._setup_skill_venv("venv_skill")

        assert mock_run.call_count == 3
        
        args_venv = mock_run.call_args_list[0][0][0]
        assert args_venv[:2] == ["uv", "venv"]
        
        args_pip = mock_run.call_args_list[1][0][0]
        assert args_pip[:4] == ["uv", "pip", "install", "-p"]

        args_compile = mock_run.call_args_list[2][0][0]
        assert args_compile[:3] == ["python", "-m", "compileall"]


def test_mcp_get_script_lazy_venv_installation(tmp_path):
    manager = SkillManager(skills_dir=str(tmp_path), allow_run_scripts=True, lazy_install_venvs=True)
    manager._agno_skills = MagicMock()
    
    skill_dir = tmp_path / "lazy_skill"
    skill_dir.mkdir()
    (skill_dir / "requirements.txt").write_text("requests")
    script_file = skill_dir / "run.py"
    script_file.write_text("print('hello')")

    with patch.object(manager, "_setup_skill_venv") as mock_setup, \
         patch("subprocess.run") as mock_run:
         
        mock_result = MagicMock()
        mock_result.stdout = "hello\n"
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        
        # When _setup_skill_venv is called, it should mock creating the python executable
        def fake_setup(*args, **kwargs):
            venv_dir = skill_dir / ".venv"
            bin_dir = venv_dir / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            (bin_dir / "python").touch()

        mock_setup.side_effect = fake_setup

        output = manager.mcp_get_script("lazy_skill", "run.py", execute=True)

        mock_setup.assert_called_once_with("lazy_skill")
        mock_run.assert_called_once()
        assert output == "hello\n"


