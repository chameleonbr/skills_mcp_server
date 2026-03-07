import base64
import io
import logging
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import List, Optional, Tuple

import httpx
from agno.skills.agent_skills import Skills
from agno.skills.loaders.local import LocalSkills
from agno.skills.skill import Skill

from models import SkillDetail, SkillSummary

logger = logging.getLogger(__name__)


class SkillManager:
    """Manages skills on disk and in-memory via Agno's Skills class.

    Handles installation, deletion, and reload of skills stored in SKILLS_DIR.
    Delegates skill access and tool generation to the Agno `Skills` orchestrator.
    """

    def __init__(self, skills_dir: str):
        self.skills_dir = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self._agno_skills: Optional[Skills] = None
        self._load()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """(Re)load skills from disk into the Agno Skills registry."""
        try:
            loader = LocalSkills(path=str(self.skills_dir), validate=False)
            self._agno_skills = Skills(loaders=[loader])
            logger.info(
                "Loaded %d skill(s) from '%s'",
                len(self._agno_skills.get_all_skills()),
                self.skills_dir,
            )
        except Exception as exc:
            logger.error("Error loading skills: %s", exc)
            # Keep empty registry so the server stays healthy
            self._agno_skills = Skills(loaders=[])

    def reload(self) -> None:
        """Reload skills from disk (called after install/update/delete)."""
        self._load()

    @property
    def agno(self) -> Skills:
        """The underlying Agno Skills instance (always non-None)."""
        if self._agno_skills is None:  # pragma: no cover
            self._load()
        return self._agno_skills  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Skill discovery
    # ------------------------------------------------------------------

    def list_skills(self) -> List[SkillSummary]:
        """Return a summary list of all loaded skills."""
        return [
            SkillSummary(
                name=s.name,
                description=s.description,
                scripts=s.scripts,
                references=s.references,
            )
            for s in self.agno.get_all_skills()
        ]

    def get_skill(self, name: str) -> Optional[SkillDetail]:
        """Return full details for a skill by name, or None if not found."""
        skill: Optional[Skill] = self.agno.get_skill(name)
        if skill is None:
            return None
        return SkillDetail(
            name=skill.name,
            description=skill.description,
            instructions=skill.instructions,
            source_path=skill.source_path,
            scripts=skill.scripts,
            references=skill.references,
            metadata=skill.metadata,
            license=skill.license,
            compatibility=skill.compatibility,
            allowed_tools=skill.allowed_tools,
        )

    # ------------------------------------------------------------------
    # Skill installation helpers
    # ------------------------------------------------------------------

    def _extract_zip_to_skills_dir(
        self, zip_bytes: bytes, unique_name: str
    ) -> Path:
        """Extract a zip archive into SKILLS_DIR/<unique_name>.

        The zip is expected to contain either:
        - A single top-level folder with SKILL.md inside, OR
        - SKILL.md directly at the root of the archive.

        Returns the path to the installed skill directory.
        """
        target_dir = self.skills_dir / unique_name

        # Remove previous version if it exists
        if target_dir.exists():
            shutil.rmtree(target_dir)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                zf.extractall(tmp_path)

            # Detect layout: single folder at root (common convention)
            children = [c for c in tmp_path.iterdir()]
            if (
                len(children) == 1
                and children[0].is_dir()
                and (children[0] / "SKILL.md").exists()
            ):
                # Move the inner folder directly
                shutil.move(str(children[0]), str(target_dir))
            else:
                # Treat root as the skill folder itself
                shutil.move(str(tmp_path), str(target_dir))

        return target_dir

    async def _fetch_zip_from_url(self, url: str) -> bytes:
        """Download a zip file from a URL and return its bytes."""
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(url, timeout=60)
            response.raise_for_status()
            return response.content

    @staticmethod
    def _parse_github_url(url: str) -> Optional[Tuple[str, str, str, Optional[str]]]:
        """Parse a GitHub URL into (owner, repo, branch, subpath).

        Supported patterns:
          https://github.com/{owner}/{repo}
          https://github.com/{owner}/{repo}/tree/{branch}
          https://github.com/{owner}/{repo}/tree/{branch}/{subpath}

        Returns:
            Tuple of (owner, repo, branch, subpath) or None if not a GitHub URL.
            subpath is None when the whole repo/branch root is targeted.
        """
        pattern = re.compile(
            r"https?://github\.com"
            r"/(?P<owner>[^/]+)"
            r"/(?P<repo>[^/]+)"
            r"(?:/tree/(?P<branch>[^/]+)(?P<subpath>/.+)?)?"
            r"/?$"
        )
        m = pattern.match(url.rstrip("/"))
        if not m:
            return None
        owner = m.group("owner")
        repo = m.group("repo")
        branch = m.group("branch") or "main"
        subpath = m.group("subpath")  # e.g. "/skills/yahoo_finance" or None
        return owner, repo, branch, subpath

    async def _fetch_github_skill(
        self, url: str
    ) -> Tuple[bytes, Optional[str]]:
        """Resolve a GitHub URL, download the zip, and return (zip_bytes, subpath).

        Args:
            url: A github.com URL pointing to a repo or a subdirectory.

        Returns:
            A tuple of (zip_bytes, subpath_inside_zip) where subpath_inside_zip
            is the path prefix to look for inside the archive (or None to use
            the whole archive).

        Raises:
            ValueError: If the URL cannot be parsed as a GitHub URL.
        """
        parsed = self._parse_github_url(url)
        if parsed is None:
            raise ValueError(f"Could not parse GitHub URL: {url!r}")

        owner, repo, branch, subpath = parsed
        zip_url = (
            f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"
        )
        logger.info(
            "Downloading GitHub archive: owner=%s repo=%s branch=%s subpath=%s",
            owner, repo, branch, subpath,
        )
        zip_bytes = await self._fetch_zip_from_url(zip_url)
        return zip_bytes, subpath

    def _extract_zip_subfolder(
        self,
        zip_bytes: bytes,
        unique_name: str,
        subpath: str,
        repo_zip_root: str,
    ) -> Path:
        """Extract a specific subfolder from a repo zip into SKILLS_DIR.

        GitHub archives have a top-level folder like ``{repo}-{branch}/``.
        We strip that prefix and then extract only the files under ``subpath``.

        Args:
            zip_bytes:     Raw bytes of the GitHub repo zip.
            unique_name:   Destination folder name inside SKILLS_DIR.
            subpath:       Path inside the repo (e.g. '/skills/yahoo_finance').
            repo_zip_root: The root prefix inside the archive (e.g. 'myrepo-main/').
        """
        # Strip leading slash and build the full prefix to match inside the zip
        clean_subpath = subpath.lstrip("/").rstrip("/")
        prefix = f"{repo_zip_root}{clean_subpath}/"

        target_dir = self.skills_dir / unique_name
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True)

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            matched = [n for n in zf.namelist() if n.startswith(prefix)]
            if not matched:
                raise FileNotFoundError(
                    f"Subpath '{clean_subpath}' not found inside the GitHub archive. "
                    f"Available top-level entries: "
                    + ", ".join({n.split("/")[1] for n in zf.namelist() if "/" in n})
                )
            for member in matched:
                # Strip the archive prefix so files land at target_dir root
                relative = member[len(prefix):]
                if not relative:  # skip the directory entry itself
                    continue
                dest = target_dir / relative
                if member.endswith("/"):
                    dest.mkdir(parents=True, exist_ok=True)
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(zf.read(member))

        return target_dir

    # ------------------------------------------------------------------
    # Public CRUD operations
    # ------------------------------------------------------------------

    async def install_skill(
        self,
        unique_name: str,
        url: Optional[str] = None,
        zip_base64: Optional[str] = None,
    ) -> Path:
        """Install a skill from a URL, GitHub link, or base64-encoded zip.

        Args:
            unique_name: The folder name to use inside SKILLS_DIR.
            url:         Remote URL of the .zip archive **or** a GitHub repo/folder URL.
                         GitHub URLs (github.com/…) are resolved automatically.
            zip_base64:  Base64-encoded .zip bytes.

        Returns:
            Path to the installed skill directory.

        Raises:
            ValueError:  If neither url nor zip_base64 is provided.
            RuntimeError: If the download or extraction fails.
        """
        if url:
            # Detect GitHub URLs and handle them specially
            if self._parse_github_url(url) is not None:
                zip_bytes, subpath = await self._fetch_github_skill(url)
                if subpath:
                    # Determine the root folder name inside the GitHub archive
                    # (GitHub names it "{repo}-{branch}/")
                    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                        repo_zip_root = zf.namelist()[0].split("/")[0] + "/"
                    skill_path = self._extract_zip_subfolder(
                        zip_bytes, unique_name, subpath, repo_zip_root
                    )
                else:
                    skill_path = self._extract_zip_to_skills_dir(zip_bytes, unique_name)
            else:
                zip_bytes = await self._fetch_zip_from_url(url)
                skill_path = self._extract_zip_to_skills_dir(zip_bytes, unique_name)
        elif zip_base64:
            zip_bytes = base64.b64decode(zip_base64)
            skill_path = self._extract_zip_to_skills_dir(zip_bytes, unique_name)
        else:
            raise ValueError("Either 'url' or 'zip_base64' must be provided.")

        self.reload()
        return skill_path

    def delete_skill(self, unique_name: str) -> bool:
        """Remove a skill directory from SKILLS_DIR.

        Args:
            unique_name: The folder name of the skill to delete.

        Returns:
            True if the skill was found and removed, False if it did not exist.
        """
        skill_dir = self.skills_dir / unique_name
        if not skill_dir.exists():
            return False
        shutil.rmtree(skill_dir)
        self.reload()
        return True

    # ------------------------------------------------------------------
    # MCP delegators (thin wrappers around Agno internals)
    # ------------------------------------------------------------------

    def mcp_get_instructions(self, skill_name: str) -> str:
        """Delegate to Agno's _get_skill_instructions."""
        return self.agno._get_skill_instructions(skill_name)

    def mcp_get_reference(self, skill_name: str, reference_path: str) -> str:
        """Delegate to Agno's _get_skill_reference."""
        return self.agno._get_skill_reference(skill_name, reference_path)

    def mcp_get_script(
        self,
        skill_name: str,
        script_path: str,
        execute: bool = False,
    ) -> str:
        """Delegate to Agno's _get_skill_script."""
        return self.agno._get_skill_script(skill_name, script_path, execute=execute)
