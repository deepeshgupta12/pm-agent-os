from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import requests

from app.core.config import settings


class GitHubAPIError(RuntimeError):
    def __init__(self, status_code: int, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details or {}


class GitHubClient:
    def __init__(self, token: Optional[str] = None):
        self.token = token or settings.GITHUB_TOKEN
        if not self.token:
            raise GitHubAPIError(401, "GITHUB_TOKEN is missing")
        self.base = "https://api.github.com"

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _get_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        r = requests.get(url, headers=self._headers(), params=params or {})
        debug = {
            "status_code": r.status_code,
            "x_ratelimit_remaining": r.headers.get("x-ratelimit-remaining"),
            "x_ratelimit_limit": r.headers.get("x-ratelimit-limit"),
        }

        if r.status_code >= 400:
            try:
                body = r.json()
            except Exception:
                body = {"message": r.text}
            raise GitHubAPIError(
                r.status_code,
                body.get("message", "GitHub API error"),
                details={"debug": debug, "body": body},
            )

        return r.json(), debug

    def list_releases(self, owner: str, repo: str, per_page: int = 20) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        url = f"{self.base}/repos/{owner}/{repo}/releases"
        return self._get_json(url, params={"per_page": per_page})

    def list_pull_requests(
        self, owner: str, repo: str, state: str = "all", per_page: int = 30
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        url = f"{self.base}/repos/{owner}/{repo}/pulls"
        return self._get_json(url, params={"state": state, "per_page": per_page, "sort": "updated"})

    def list_issues(
        self, owner: str, repo: str, state: str = "all", per_page: int = 50
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        GitHub issues API returns BOTH issues and PRs. We'll filter PRs out at ingestion time.
        """
        url = f"{self.base}/repos/{owner}/{repo}/issues"
        return self._get_json(url, params={"state": state, "per_page": per_page, "sort": "updated", "direction": "desc"})