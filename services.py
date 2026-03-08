import base64
import io
import logging
import re
import shutil
import tempfile
import zipfile
import platform
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx
from agno.skills.agent_skills import Skills
from agno.skills.loaders.local import LocalSkills
from agno.skills.skill import Skill

from models import SkillDetail, SkillSummary
from s3_skills import S3Skills

logger = logging.getLogger(__name__)


class SkillManager:
    """Manages skills on disk and in-memory via Agno's Skills class.

    Handles installation, deletion, and reload of skills stored in SKILLS_DIR.
    Delegates skill access and tool generation to the Agno `Skills` orchestrator.

    Args:
        skills_dir:    Path to the local skills directory (used by LocalSkills).
        storage_mode:  ``"local"`` (default) or ``"s3"``.
                       When ``"s3"``, S3Skills is used as the loader instead of LocalSkills.
        s3_bucket:     S3 bucket name (required when storage_mode="s3").
        s3_prefix:     Key prefix inside the bucket (default: ``"skills/"``).
        s3_cache_dir:  Local directory where S3 objects are cached (default: ``".s3cache"``).
        s3_region:     Optional AWS region name.
        s3_endpoint:   Optional custom endpoint URL (MinIO, LocalStack…).
        allow_run_scripts: Whether to allow script execution (default: False).
    """

    def __init__(
        self,
        skills_dir: str,
        storage_mode: str = "local",
        s3_bucket: Optional[str] = None,
        s3_prefix: str = "skills/",
        s3_cache_dir: str = ".s3cache",
        s3_region: Optional[str] = None,
        s3_endpoint: Optional[str] = None,
        allow_run_scripts: bool = False,
        lazy_install_venvs: bool = False,
    ):
        self.skills_dir = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.storage_mode = storage_mode.lower()
        self.s3_bucket = s3_bucket
        self.s3_prefix = s3_prefix
        self.s3_cache_dir = s3_cache_dir
        self.s3_region = s3_region
        self.s3_endpoint = s3_endpoint
        self.allow_run_scripts = allow_run_scripts
        self.lazy_install_venvs = lazy_install_venvs
        self._agno_skills: Optional[Skills] = None
        self._load()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """(Re)load skills into the Agno Skills registry using the configured loader."""
        try:
            if self.storage_mode == "s3":
                if not self.s3_bucket:
                    raise ValueError(
                        "SKILLS_STORAGE=s3 requires S3_BUCKET to be configured."
                    )
                loader = S3Skills(
                    bucket=self.s3_bucket,
                    prefix=self.s3_prefix,
                    cache_dir=self.s3_cache_dir,
                    validate=False,
                    region_name=self.s3_region,
                    endpoint_url=self.s3_endpoint,
                )
                logger.info(
                    "Using S3Skills loader (s3://%s/%s → %s)",
                    self.s3_bucket, self.s3_prefix, self.s3_cache_dir,
                )
            else:
                loader = LocalSkills(path=str(self.skills_dir), validate=False)
                logger.info("Using LocalSkills loader (%s)", self.skills_dir)

            self._agno_skills = Skills(loaders=[loader])
            logger.info(
                "Loaded %d skill(s)",
                len(self._agno_skills.get_all_skills()),
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

    def _setup_skill_venv(self, skill_name: str) -> None:
        """Create a virtual environment and install requirements for a skill, if needed."""
        skill_dir = self.skills_dir / skill_name
        req_files = list(skill_dir.rglob("requirements.txt"))
        if not req_files:
            return

        venv_dir = skill_dir / ".venv"
        logger.info("Creating uv venv for skill %s at %s", skill_name, venv_dir)
        try:
            subprocess.run(["uv", "venv", str(venv_dir)], check=True, capture_output=True)
            
            cmd = ["uv", "pip", "install", "-p", str(venv_dir)]
            for req in req_files:
                cmd.extend(["-r", str(req)])
                
            logger.info("Installing requirements for skill %s", skill_name)
            subprocess.run(cmd, check=True, capture_output=True)

            logger.info("Pre-compiling .pyc for faster startup in skill %s", skill_name)
            subprocess.run(["python", "-m", "compileall", "-b", str(skill_dir)], capture_output=True)
            
        except subprocess.CalledProcessError as e:
            err_msg = e.stderr.decode("utf-8", errors="replace") if e.stderr else str(e)
            logger.error("Failed to setup venv for skill %s: %s", skill_name, err_msg)
            raise RuntimeError(f"Failed to setup venv for skill '{skill_name}': {err_msg}")

    async def _install_from_index(self, url: str) -> List[str]:
        """Fetch and install skills defined in a Cloudflare RFC skills_index.json.

        Args:
            url: URL to the `skills_index.json` file.

        Returns:
            A list of installed skill names.
            
        Raises:
            ValueError: If the JSON format is invalid.
            FileExistsError: If one of the skills already exists locally.
        """
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()

        skills = data.get("skills")
        if not isinstance(skills, list):
            raise ValueError("index.json must contain a 'skills' array.")

        def _get_all_file_paths(f_obj) -> List[str]:
            if isinstance(f_obj, str):
                return [f_obj]
            elif isinstance(f_obj, list):
                res = []
                for x in f_obj:
                    res.extend(_get_all_file_paths(x))
                return res
            elif isinstance(f_obj, dict):
                res = []
                for v in f_obj.values():
                    res.extend(_get_all_file_paths(v))
                return res
            return []

        installed_names = []
        base_url = url.rsplit("/", 1)[0]

        for skill_def in skills:
            name = skill_def.get("name")
            raw_files = skill_def.get("files", [])
            file_paths = _get_all_file_paths(raw_files)
            
            if not name or not file_paths:
                continue
                
            skill_dir = self.skills_dir / name
            if skill_dir.exists():
                raise FileExistsError(
                    f"Skill '{name}' already exists. Please delete it first."
                )

            # Download files to a temp directory first to ensure atomic install
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                for file_path in file_paths:
                    file_url = f"{base_url}/{file_path.lstrip('/')}"
                    async with httpx.AsyncClient(follow_redirects=True) as client:
                        file_resp = await client.get(file_url, timeout=30)
                        file_resp.raise_for_status()
                        
                    dest = tmp_path / file_path.lstrip('/')
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(file_resp.content)
                
                # Locate SKILL.md dynamically
                skill_md_files = list(tmp_path.rglob("SKILL.md"))
                if not skill_md_files:
                    raise FileNotFoundError(f"SKILL.md not found in downloaded index for '{name}'.")
                
                # Sort by path length to pick the top-level SKILL.md first
                skill_md_files.sort(key=lambda p: len(p.parts))
                    
                skill_md_path = skill_md_files[0]
                source_dir = skill_md_path.parent
                
                content = skill_md_path.read_text(encoding="utf-8")
                m = re.search(r"^name:\s*([^\r\n]+)", content, re.MULTILINE)
                if not m:
                    raise ValueError(f"Could not find 'name:' in SKILL.md frontmatter for '{name}'.")
                
                parsed_name = m.group(1).strip().strip("\"'")
                if parsed_name != name:
                    logger.warning("Index name '%s' differs from SKILL.md name '%s'", name, parsed_name)

                shutil.move(str(source_dir), str(skill_dir))
                if not self.lazy_install_venvs:
                    self._setup_skill_venv(parsed_name)
                installed_names.append(parsed_name)

        return installed_names

    def _extract_and_install_skills(
        self,
        zip_bytes: bytes,
        subpath: Optional[str] = None,
        repo_zip_root: Optional[str] = None,
    ) -> List[str]:
        """Extract a zip archive and recursively install all found skills.

        Args:
            zip_bytes:     Raw zip bytes.
            subpath:       Optional github repo subpath (e.g. '/skills').
            repo_zip_root: Optional prefix for github repos (e.g. 'myrepo-main/').

        Returns:
            A list of installed skill names.
        """
        prefix = ""
        if subpath and repo_zip_root:
            clean_subpath = subpath.lstrip("/").rstrip("/")
            prefix = f"{repo_zip_root}{clean_subpath}/"
            
        installed_names = []
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                if prefix:
                    matched = [n for n in zf.namelist() if n.startswith(prefix)]
                    if not matched:
                        raise FileNotFoundError(f"Subpath '{subpath}' not found inside archive.")
                    for member in matched:
                        relative = member[len(prefix):]
                        if not relative:
                            continue
                        dest = tmp_path / relative
                        if member.endswith("/"):
                            dest.mkdir(parents=True, exist_ok=True)
                        else:
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            dest.write_bytes(zf.read(member))
                else:
                    zf.extractall(tmp_path)

            # Recursively find all SKILL.md files
            skill_md_files = list(tmp_path.rglob("SKILL.md"))
            if not skill_md_files:
                raise FileNotFoundError("No SKILL.md found in the uploaded archive.")

            # Sort by path length to process top-level skills first
            skill_md_files.sort(key=lambda p: len(p.parts))

            for skill_md_path in skill_md_files:
                if not skill_md_path.exists():
                    continue

                source_dir = skill_md_path.parent
                content = skill_md_path.read_text(encoding="utf-8")
                
                m = re.search(r"^name:\s*([^\r\n]+)", content, re.MULTILINE)
                if not m:
                    raise ValueError(f"Could not find 'name:' in {skill_md_path} frontmatter.")
                
                skill_name = m.group(1).strip().strip("\"'")
                target_dir = self.skills_dir / skill_name
                
                if target_dir.exists():
                    raise FileExistsError(
                        f"Skill '{skill_name}' already exists. Please delete it first."
                    )
                    
                shutil.move(str(source_dir), str(target_dir))
                if not self.lazy_install_venvs:
                    self._setup_skill_venv(skill_name)
                installed_names.append(skill_name)

        return installed_names

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



    # ------------------------------------------------------------------
    # Public CRUD operations
    # ------------------------------------------------------------------

    async def install_skill(
        self,
        url: Optional[str] = None,
        zip_base64: Optional[str] = None,
    ) -> List[str]:
        """Install one or more skills from a URL, GitHub link, base64 encoded zip, or Discovery JSON.

        Extracts the skill names from the `SKILL.md` files.

        Args:
            url:         Remote URL of the .zip archive, GitHub repo/folder URL, or skills_index.json.
            zip_base64:  Base64-encoded .zip bytes.

        Returns:
            List of installed skill names.

        Raises:
            ValueError:  If neither url nor zip_base64 is provided.
            FileExistsError: If a skill with the parsed name already exists.
            RuntimeError: If the download or extraction fails.
        """
        if url:
            # Convert GitHub repo blob URLs to raw content URLs so files can be fetched directly
            if url.startswith("https://github.com/") and "/blob/" in url:
                url = url.replace("https://github.com/", "https://raw.githubusercontent.com/").replace("/blob/", "/")

            if url.endswith(".json"):
                installed_names = await self._install_from_index(url)
            elif self._parse_github_url(url) is not None:
                zip_bytes, subpath = await self._fetch_github_skill(url)
                if subpath:
                    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                        repo_zip_root = zf.namelist()[0].split("/")[0] + "/"
                    installed_names = self._extract_and_install_skills(
                        zip_bytes, subpath=subpath, repo_zip_root=repo_zip_root
                    )
                else:
                    installed_names = self._extract_and_install_skills(zip_bytes)
            else:
                zip_bytes = await self._fetch_zip_from_url(url)
                installed_names = self._extract_and_install_skills(zip_bytes)
        elif zip_base64:
            zip_bytes = base64.b64decode(zip_base64)
            installed_names = self._extract_and_install_skills(zip_bytes)
        else:
            raise ValueError("Either 'url' or 'zip_base64' must be provided.")

        self.reload()
        return installed_names

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

    def delete_all_skills(self) -> int:
        """Remove all skill directories from SKILLS_DIR.

        Returns:
            The number of skills that were removed.
        """
        count = 0
        if self.skills_dir.exists():
            for skill_dir in self.skills_dir.iterdir():
                if skill_dir.is_dir():
                    shutil.rmtree(skill_dir)
                    count += 1
        if count > 0:
            self.reload()
        return count

    # ------------------------------------------------------------------
    # MCP delegators (thin wrappers around Agno internals)
    # ------------------------------------------------------------------

    def _validate_safe_name(self, name: str, param_name: str = "name") -> None:
        """Ensure name contains only safe characters."""
        if not re.match(r"^[a-zA-Z0-9_\-]+$", name):
            raise ValueError(f"Invalid {param_name} format: {name}")

    def _validate_safe_path(self, path: str, param_name: str = "path") -> None:
        """Ensure path does not contain directory traversal or absolute paths."""
        if ".." in path or path.startswith("/") or path.startswith("\\"):
            raise ValueError(f"Invalid {param_name}. Directory traversal and absolute paths are not allowed.")

    def mcp_get_instructions(self, skill_name: str) -> str:
        """Delegate to Agno's _get_skill_instructions."""
        self._validate_safe_name(skill_name, "skill_name")
        return self.agno._get_skill_instructions(skill_name)

    def mcp_get_reference(self, skill_name: str, reference_path: str) -> str:
        """Delegate to Agno's _get_skill_reference."""
        self._validate_safe_name(skill_name, "skill_name")
        self._validate_safe_path(reference_path, "reference_path")
        return self.agno._get_skill_reference(skill_name, reference_path)

    def mcp_get_script(
        self,
        skill_name: str,
        script_path: str,
        execute: bool = False,
        args: Optional[List[str]] = None,
    ) -> str:
        """Delegate to Agno's _get_skill_script."""
        self._validate_safe_name(skill_name, "skill_name")
        self._validate_safe_path(script_path, "script_path")

        if execute:
            if not self.allow_run_scripts:
                raise ValueError("Script execution is disabled by configuration (ALLOW_RUN_SCRIPTS=false).")
            if args:
                forbidden_chars = set("&|;$><`\\n\\r")
                for arg in args:
                    if any(c in forbidden_chars for c in arg):
                        raise ValueError(f"Argument contains forbidden shell characters: {arg}")

            skill_dir = self.skills_dir / skill_name
            venv_dir = skill_dir / ".venv"

            if not venv_dir.exists() and list(skill_dir.rglob("requirements.txt")):
                logger.info("Checking for lazy venv installation before executing skill %s", skill_name)
                self._setup_skill_venv(skill_name)

            venv_python = venv_dir / "bin" / "python"
            if not venv_python.exists():
                venv_python = venv_dir / "Scripts" / "python.exe"

            target_script = skill_dir / script_path
            if venv_python.exists() and target_script.suffix.lower() == ".py":
                # Execute Python via subprocess without -S to ensure site-packages (like 'requests') are loaded correctly
                cmd = [str(venv_python), str(target_script)] + (args or [])
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                    stdout = result.stdout or ""
                    stderr = result.stderr or ""
                    if stderr:
                        return f"Error executing script:\n{stderr}\n\nStdout:\n{stdout}"
                    return stdout
                except subprocess.TimeoutExpired:
                    return "Error: Script execution timed out."
                except Exception as e:
                    return f"Error executing script: {str(e)}"

            from agno.skills.utils import ensure_executable
            if platform.system() != "Windows":
                ensure_executable(target_script)

        return self.agno._get_skill_script(skill_name, script_path, execute=execute, args=args)

    def get_system_prompt_snippet(self, skill_list: Optional[List[str]] = None) -> str:
        """Generate a system prompt snippet filtered by an optional blocklist/allowlist.
        
        Args:
            skill_list: Optional list of skill names to include. If provided, only these will be returned.
            
        Returns:
            XML-formatted snippet string.
        """
        if skill_list is None:
            return self.agno.get_system_prompt_snippet()
            
        logger.info(f"Filtering skills to: {skill_list}")
        # Create a disposable Skills instance to reliably format the snippet
        # only including the skills requested
        filtered_agno = Skills(loaders=[])
        
        # Manually populate its internal dictionary from our fully loaded one
        for skill_name in skill_list:
            clean_name = skill_name.strip()
            skill_obj = self.agno.get_skill(clean_name)
            logger.info(f"Looking for skill '{clean_name}': Found={skill_obj is not None}")
            if skill_obj:
                filtered_agno._skills[clean_name] = skill_obj
                
        logger.info(f"Filtered dictionary has keys: {list(filtered_agno._skills.keys())}")
        return filtered_agno.get_system_prompt_snippet()
