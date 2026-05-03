"""
Database module: manages persistence of job listings in jobs_archive.json.

The archive has the structure:
{
    "CompanyName": {
        "<hash>": {"title": "...", "link": "...", "hash": "..."},
        ...
    },
    ...
}
"""

import json
import os
from typing import Optional

DEFAULT_ARCHIVE_PATH = "jobs_archive.json"


class DatabaseManager:
    """Manages reading and writing of the jobs archive JSON file."""

    def __init__(self, archive_path: str = DEFAULT_ARCHIVE_PATH) -> None:
        self._path = archive_path
        self._data: dict[str, dict[str, dict]] = {}
        self._load()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load archive from disk.  Creates an empty archive if missing."""
        if os.path.exists(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as fh:
                    self._data = json.load(fh)
            except (json.JSONDecodeError, OSError) as exc:
                print(f"  [db] Warning: could not read archive ({exc}). Starting fresh.")
                self._data = {}
        else:
            self._data = {}

    def _save(self) -> None:
        """Persist the current in-memory archive to disk."""
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_archived_jobs(self, company: str) -> dict[str, dict]:
        """Return the archived job map ``{hash: job_dict}`` for *company*."""
        return dict(self._data.get(company, {}))

    def update_company(self, company: str, jobs: list[dict]) -> None:
        """
        Replace the stored jobs for *company* with the given list.

        Each item in *jobs* must have a "hash" key.
        """
        self._data[company] = {job["hash"]: job for job in jobs}
        self._save()

    def all_companies(self) -> list[str]:
        """Return the list of companies currently stored in the archive."""
        return list(self._data.keys())

    # ------------------------------------------------------------------
    # Comparison helpers
    # ------------------------------------------------------------------

    @staticmethod
    def find_new_jobs(
        current: list[dict],
        archived: dict[str, dict],
    ) -> list[dict]:
        """
        Return jobs from *current* whose hash is not present in *archived*.
        """
        return [job for job in current if job["hash"] not in archived]

    @staticmethod
    def find_closed_jobs(
        current: list[dict],
        archived: dict[str, dict],
    ) -> list[dict]:
        """
        Return archived jobs whose hash is no longer present in *current*.
        """
        current_hashes = {job["hash"] for job in current}
        return [
            job
            for hash_key, job in archived.items()
            if hash_key not in current_hashes
        ]
