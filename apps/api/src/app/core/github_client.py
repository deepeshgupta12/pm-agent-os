from __future__ import annotations

from typing import Any, Dict, List, Optional
import requests

from app.core.config import settings


class GitHubClient:
    def __init__(self, token: Optional[str] = None):
        self.token = token or settings.GITHUB_TOKEN
        if not self.token:
            raise RuntimeError("GITHUB_TOKEN is missing")
        self.base = "https://api.github.com"

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def list_releases(self, owner: str, repo: str, per_page: int = 20) -> List[Dict[str, Any]]:
        url = f"{self.base}/repos/{owner}/{repo}/releases"
        r = requests.get(url, headers=self._headers(), params={"per_page": per_page})
        r.raise_for_status()
        return r.json()

    def list_pull_requests(self, owner: str, repo: str, state: str = "all", per_page: int = 30) -> List[Dict[str, Any]]:
        url = f"{self.base}/repos/{owner}/{repo}/pulls"
        r = requests.get(url, headers=self._headers(), params={"state": state, "per_page": per_page, "sort": "updated"})
        r.raise_for_status()
        return r.json()