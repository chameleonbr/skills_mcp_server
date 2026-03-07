"""MCP server module.

Exposes skill-access tools via FastMCP:
  - get_available_skills: list all loaded skills
  - get_skill_instructions: load full instructions for a skill
  - get_skill_reference:    access a reference document from a skill
  - get_skill_script:       read or execute a script from a skill
"""
import logging
from typing import Callable

from fastmcp import FastMCP

from services import SkillManager

logger = logging.getLogger(__name__)


def create_mcp_server(get_manager: Callable[[], SkillManager]) -> FastMCP:
    """Create and configure the FastMCP server with Agno skill tools.

    Args:
        get_manager: A zero-argument callable that returns the current
                     SkillManager instance. Using a callable (instead of
                     passing the manager directly) ensures that tools always
                     resolve the *live* instance even after it is replaced
                     or reloaded during the lifespan of the application.

    Returns:
        A configured FastMCP instance ready to be mounted on FastAPI.
    """
    mcp = FastMCP(
        name="Skills MCP Server",
        instructions=(
            "This server exposes agent skills. "
            "Use get_skill_instructions(skill_name) to load the full guidance "
            "for the skill that matches your task."
        ),
    )

    # -----------------------------------------------------------------------
    # Tool: get_available_skills
    # -----------------------------------------------------------------------

    @mcp.tool
    def get_available_skills() -> str:
        """Return a list of all currently loaded skills with their name and description.

        Call this first to discover which skills are available before invoking
        any other skill tool.
        """
        logger.debug("MCP tool: get_available_skills()")
        return get_manager().agno.get_system_prompt_snippet()

    # -----------------------------------------------------------------------
    # Tool: get_skill_instructions
    # -----------------------------------------------------------------------

    @mcp.tool
    def get_skill_instructions(skill_name: str) -> str:
        """Load the full instructions for a skill.

        Use this when you need to follow a skill's guidance. Returns a JSON
        string with the skill's name, description, instructions, available
        scripts, and available references.

        Args:
            skill_name: The unique name of the skill (as returned by
                        get_available_skills).
        """
        logger.debug("MCP tool: get_skill_instructions(skill_name=%r)", skill_name)
        return get_manager().mcp_get_instructions(skill_name)

    # -----------------------------------------------------------------------
    # Tool: get_skill_reference
    # -----------------------------------------------------------------------

    @mcp.tool
    def get_skill_reference(skill_name: str, reference_path: str) -> str:
        """Load a reference document from a skill's references directory.

        Use this to access detailed documentation files listed in a skill's
        available_references. Returns a JSON string with the document content.

        Args:
            skill_name:     The unique name of the skill.
            reference_path: Filename of the reference document (e.g. 'guide.md').
        """
        logger.debug(
            "MCP tool: get_skill_reference(skill_name=%r, reference_path=%r)",
            skill_name,
            reference_path,
        )
        return get_manager().mcp_get_reference(skill_name, reference_path)

    # -----------------------------------------------------------------------
    # Tool: get_skill_script
    # -----------------------------------------------------------------------

    @mcp.tool
    def get_skill_script(
        skill_name: str,
        script_path: str,
        execute: bool = False,
    ) -> str:
        """Read or execute a script from a skill.

        Set execute=False (default) to read the script content.
        Set execute=True to run the script and capture its stdout/stderr.

        Args:
            skill_name:  The unique name of the skill.
            script_path: Filename of the script (e.g. 'run.py').
            execute:     Whether to execute the script (default: False).
        """
        logger.debug(
            "MCP tool: get_skill_script(skill_name=%r, script_path=%r, execute=%r)",
            skill_name,
            script_path,
            execute,
        )
        return get_manager().mcp_get_script(skill_name, script_path, execute=execute)

    return mcp
