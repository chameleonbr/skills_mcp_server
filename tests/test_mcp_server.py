import json
import pytest
from mcp_server import create_mcp_server
from services import SkillManager

def test_mcp_server_initialization():
    mcp = create_mcp_server(lambda: None)
    assert mcp.name == "Skills MCP Server"
