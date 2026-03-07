import os
import sys
import pytest

# Add the project root to the path so we can import our modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from main import app
from routes import get_skill_manager
from services import SkillManager

@pytest.fixture
def mock_skill_manager():
    """Returns a MagicMock simulating the SkillManager."""
    mock = MagicMock(spec=SkillManager)
    
    # Setup some default successful returns
    mock.list_skills.return_value = []
    mock.get_system_prompt_snippet.return_value = "<skills_system></skills_system>"
    
    return mock

@pytest.fixture
def test_client(mock_skill_manager):
    """Returns a FastAPI TestClient with mocked dependencies."""
    app.dependency_overrides[get_skill_manager] = lambda: mock_skill_manager
    
    # FastMCP lifespan runs exactly once. To avoid triggering lifespan
    # multiple times in multiple tests, we create TestClient without a with-block
    # because we don't need the lifespan tasks to test our REST routes.
    import routes
    routes._expected_api_key = "skills_secret_key"
    client = TestClient(app, headers={"X-API-Key": "skills_secret_key"})
    yield client
        
    app.dependency_overrides.clear()
