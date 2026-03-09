import pytest
import io
from fastapi import status

def test_list_skills(test_client, mock_skill_manager):
    # Setup mock
    from models import SkillSummary
    mock_skill_manager.list_skills.return_value = [
        SkillSummary(name="skill1", description="desc1"), 
        SkillSummary(name="skill2", description="desc2")
    ]
    
    response = test_client.get("/skills")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data) == 2
    assert data[0]["name"] == "skill1"

def test_get_skill(test_client, mock_skill_manager):
    # Setup mock
    from models import SkillDetail
    mock_skill_manager.get_skill.return_value = SkillDetail(
        name="skill1", 
        description="test obj", 
        instructions="test instructions",
        source_path="skills/skill1"
    )
    
    response = test_client.get("/skills/skill1")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["name"] == "skill1"

def test_get_skill_not_found(test_client, mock_skill_manager):
    mock_skill_manager.get_skill.return_value = None
    
    response = test_client.get("/skills/unknown_skill")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "not found" in response.json()["detail"].lower()

@pytest.mark.asyncio
async def test_add_skill_url(test_client, mock_skill_manager):
    mock_skill_manager.install_skill.return_value = ["new_skill"]
    
    response = test_client.post("/skills", json={"url": "https://example.com/skill.zip"})
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["message"] == "Successfully installed 1 skill(s)."
    assert data["installed_skills"] == ["new_skill"]
    mock_skill_manager.install_skill.assert_called_once_with(url="https://example.com/skill.zip", zip_base64=None)

@pytest.mark.asyncio
async def test_add_skill_base64(test_client, mock_skill_manager):
    mock_skill_manager.install_skill.return_value = ["new_skill"]
    
    response = test_client.post("/skills", json={"zip_base64": "UE..."})
    assert response.status_code == status.HTTP_201_CREATED
    mock_skill_manager.install_skill.assert_called_once_with(url=None, zip_base64="UE...")

def test_add_skill_conflict(test_client, mock_skill_manager):
    mock_skill_manager.install_skill.side_effect = FileExistsError("Skill already exists")
    
    response = test_client.post("/skills", json={"url": "https://example.com/skill.zip"})
    assert response.status_code == status.HTTP_409_CONFLICT
    assert "Skill already exists" in response.json()["detail"]

@pytest.mark.asyncio
async def test_upload_skill(test_client, mock_skill_manager):
    mock_skill_manager._extract_and_install_skills.return_value = ["uploaded_skill"]
    
    file_content = b"fakezipcontent"
    files = {"file": ("test.zip", file_content, "application/zip")}
    
    response = test_client.post("/skills/upload", files=files)
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert "uploaded_skill" in data["installed_skills"]
    assert mock_skill_manager._extract_and_install_skills.call_count == 1

def test_delete_skill(test_client, mock_skill_manager):
    mock_skill_manager.delete_skill.return_value = True
    
    response = test_client.delete("/skills/skill1")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["message"] == "Skill 'skill1' deleted successfully."
    mock_skill_manager.delete_skill.assert_called_once_with("skill1")

def test_delete_skill_not_found(test_client, mock_skill_manager):
    mock_skill_manager.delete_skill.return_value = False
    
    response = test_client.delete("/skills/skill1")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "not found" in response.json()["detail"]

def test_prompt_snippet(test_client, mock_skill_manager):
    mock_skill_manager.get_system_prompt_snippet.return_value = "<skills_system>test</skills_system>"
    
    response = test_client.get("/skills/prompt_snippet")
    assert response.status_code == status.HTTP_200_OK
    assert "test" in response.json()
    mock_skill_manager.get_system_prompt_snippet.assert_called_once_with(None)

def test_prompt_snippet_with_filter(test_client, mock_skill_manager):
    mock_skill_manager.get_system_prompt_snippet.return_value = "<skills_system>filtered</skills_system>"
    
    response = test_client.get("/skills/prompt_snippet?skill_list=skill1,skill2")
    assert response.status_code == status.HTTP_200_OK
    mock_skill_manager.get_system_prompt_snippet.assert_called_once_with(["skill1", "skill2"])


def test_prompt_snippet_post(test_client, mock_skill_manager):
    mock_skill_manager.get_system_prompt_snippet.return_value = "<skills_system>post_snippet</skills_system>"
    
    # We pass some arbitrary JSON body
    payload = {"custom_field": "hello world", "nested": {"a": 1}}
    
    response = test_client.post("/skills/prompt_snippet?skill_list=skill1", json=payload)
    assert response.status_code == status.HTTP_200_OK
    
    data = response.json()
    assert data["custom_field"] == "hello world"
    assert data["nested"]["a"] == 1
    assert data["prompt"] == "<skills_system>post_snippet</skills_system>"
    mock_skill_manager.get_system_prompt_snippet.assert_called_once_with(["skill1"])
