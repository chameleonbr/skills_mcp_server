"""S3Skills — Agno SkillLoader that syncs skill folders from an S3 bucket.

Usage::

    from s3_skills import S3Skills
    from agno.skills.agent_skills import Skills

    loader = S3Skills(
        bucket="my-bucket",
        prefix="skills/",          # top-level prefix inside the bucket
        cache_dir=".s3cache",      # local folder where objects are downloaded
    )
    skills = Skills(loaders=[loader])

The loader:
1. Lists all S3 objects under ``{bucket}/{prefix}``.
2. Downloads them into ``cache_dir`` (mirroring the key path relative to prefix).
3. Delegates to ``LocalSkills(cache_dir)`` to parse and return ``Skill`` objects.

Requires ``boto3`` to be installed (``pip install boto3``).
AWS credentials are read from the standard boto3 chain
(env vars, ~/.aws/credentials, IAM role, etc.).
Use ``AWS_ENDPOINT_URL`` for MinIO / LocalStack compatibility.
"""

import logging
from pathlib import Path
from typing import List, Optional

from agno.skills.loaders.base import SkillLoader
from agno.skills.loaders.local import LocalSkills
from agno.skills.skill import Skill

logger = logging.getLogger(__name__)


class S3Skills(SkillLoader):
    """Load skills from an S3 bucket by syncing them to a local cache directory.

    Args:
        bucket:       S3 bucket name.
        prefix:       Key prefix that acts as the remote skills root (e.g. ``"skills/"``).
                      Objects must be structured as ``{prefix}{skill_name}/SKILL.md``.
        cache_dir:    Local directory where S3 objects are downloaded.
                      Defaults to ``.s3cache`` in the current working directory.
        validate:     Whether to validate skills after loading (passed to LocalSkills).
        region_name:  Optional AWS region override.
        endpoint_url: Optional custom endpoint (MinIO, LocalStack, etc.).
    """

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        cache_dir: str = ".s3cache",
        validate: bool = False,
        region_name: Optional[str] = None,
        endpoint_url: Optional[str] = None,
    ):
        self.bucket = bucket
        self.prefix = prefix.rstrip("/") + "/" if prefix else ""
        self.cache_dir = Path(cache_dir).resolve()
        self.validate = validate
        self.region_name = region_name
        self.endpoint_url = endpoint_url

    # ------------------------------------------------------------------
    # SkillLoader interface
    # ------------------------------------------------------------------

    def load(self) -> List[Skill]:
        """Sync skills from S3 and return parsed Skill objects.

        Returns:
            A list of Skill objects loaded from the S3 bucket.

        Raises:
            ImportError:  If boto3 is not installed.
            RuntimeError: If the S3 sync fails.
        """
        self._sync_from_s3()
        local_loader = LocalSkills(path=str(self.cache_dir), validate=self.validate)
        skills = local_loader.load()
        logger.info(
            "S3Skills: loaded %d skill(s) from s3://%s/%s → %s",
            len(skills),
            self.bucket,
            self.prefix,
            self.cache_dir,
        )
        return skills

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_s3_client(self):
        """Create and return a boto3 S3 client."""
        try:
            import boto3
        except ImportError as exc:
            raise ImportError(
                "boto3 is required for S3Skills. Install it with: pip install boto3"
            ) from exc

        kwargs = {}
        if self.region_name:
            kwargs["region_name"] = self.region_name
        if self.endpoint_url:
            kwargs["endpoint_url"] = self.endpoint_url

        return boto3.client("s3", **kwargs)

    def _sync_from_s3(self) -> None:
        """List and download all S3 objects under the configured prefix.

        Recreates the remote directory structure under ``cache_dir``.
        Files already present locally are overwritten to ensure freshness.
        """
        client = self._get_s3_client()
        paginator = client.get_paginator("list_objects_v2")

        downloaded = 0
        pages = paginator.paginate(Bucket=self.bucket, Prefix=self.prefix)

        for page in pages:
            for obj in page.get("Contents", []):
                key: str = obj["Key"]

                # Strip the bucket prefix to get relative path
                relative_key = key[len(self.prefix):]

                # Skip "directory" entries (keys ending with /)
                if not relative_key or relative_key.endswith("/"):
                    continue

                local_path = self.cache_dir / relative_key
                local_path.parent.mkdir(parents=True, exist_ok=True)

                logger.debug("S3Skills: downloading s3://%s/%s → %s", self.bucket, key, local_path)
                client.download_file(self.bucket, key, str(local_path))
                downloaded += 1

        logger.info(
            "S3Skills: synced %d file(s) from s3://%s/%s",
            downloaded,
            self.bucket,
            self.prefix,
        )

        if downloaded == 0:
            logger.warning(
                "S3Skills: no objects found under s3://%s/%s — bucket empty or prefix wrong?",
                self.bucket,
                self.prefix,
            )
            # Ensure cache_dir exists so LocalSkills doesn't raise FileNotFoundError
            self.cache_dir.mkdir(parents=True, exist_ok=True)
