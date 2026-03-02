from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import time
import random

import requests

from app.core.config import settings


class GitHubAPIError(RuntimeError):
    def __init__(self, status_code: int, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details or {}


@dataclass
class _RetryPolicy:
    max_retries: int = 5
    base_sleep_s: float = 0.8
    max_sleep_s: float = 12.0
    reset_sleep_cap_s: float = 60.0  # don't sleep more than this per request


class GitHubClient:
    """
    V1.5:
      - Pagination beyond per_page (page loop with max_pages/max_items)
      - Rate limit / backoff:
          * retry 429 + 5xx
          * handle X-RateLimit-Remaining=0 with sleep until X-RateLimit-Reset (capped)
          * honor Retry-After if present
    """

    def __init__(
        self,
        token: Optional[str] = None,
        *,
        timeout_s: int = 30,
        retry: Optional[_RetryPolicy] = None,
    ):
        self.token = token or settings.GITHUB_TOKEN
        if not self.token:
            raise GitHubAPIError(401, "GITHUB_TOKEN is missing")

        self.base = "https://api.github.com"
        self.timeout_s = int(timeout_s)
        self.retry = retry or _RetryPolicy()

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "pm-agent-os/1.0",
            }
        )

    def _maybe_sleep_for_primary_rate_limit(self, r: requests.Response) -> Optional[float]:
        """
        GitHub primary rate limit:
          - often 403
          - X-RateLimit-Remaining: 0
          - X-RateLimit-Reset: epoch seconds
        """
        remaining = r.headers.get("X-RateLimit-Remaining") or r.headers.get("x-ratelimit-remaining")
        reset = r.headers.get("X-RateLimit-Reset") or r.headers.get("x-ratelimit-reset")
        if remaining is None or reset is None:
            return None

        try:
            remaining_i = int(remaining)
            reset_i = int(reset)
        except Exception:
            return None

        if remaining_i > 0:
            return None

        now = int(time.time())
        sleep_for = max(0, reset_i - now)
        sleep_for = min(float(sleep_for), float(self.retry.reset_sleep_cap_s))
        if sleep_for > 0:
            time.sleep(sleep_for)
        return sleep_for

    def _retry_sleep(self, attempt: int, retry_after: Optional[str] = None) -> float:
        if retry_after:
            try:
                s = float(retry_after)
                s = max(0.0, min(s, self.retry.max_sleep_s))
                time.sleep(s)
                return s
            except Exception:
                pass

        # exponential backoff + small jitter
        base = self.retry.base_sleep_s * (2 ** max(0, attempt - 1))
        jitter = random.uniform(0.0, 0.25 * base)
        s = min(self.retry.max_sleep_s, base + jitter)
        time.sleep(s)
        return s

    def _request_json(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Any, Dict[str, Any]]:
        last_err: Optional[GitHubAPIError] = None

        for attempt in range(1, self.retry.max_retries + 1):
            r = self.session.get(url, params=params or {}, timeout=self.timeout_s)

            debug = {
                "status_code": r.status_code,
                "x_ratelimit_remaining": r.headers.get("x-ratelimit-remaining") or r.headers.get("X-RateLimit-Remaining"),
                "x_ratelimit_limit": r.headers.get("x-ratelimit-limit") or r.headers.get("X-RateLimit-Limit"),
                "x_ratelimit_reset": r.headers.get("x-ratelimit-reset") or r.headers.get("X-RateLimit-Reset"),
                "retry_after": r.headers.get("Retry-After"),
                "attempt": attempt,
                "url": url,
                "params": params or {},
            }

            # success
            if 200 <= r.status_code < 300:
                try:
                    return r.json(), debug
                except Exception:
                    raise GitHubAPIError(r.status_code, "GitHub returned non-JSON response", {"debug": debug, "text": r.text})

            # primary rate limit
            if r.status_code == 403:
                slept = self._maybe_sleep_for_primary_rate_limit(r)
                if slept is not None and attempt < self.retry.max_retries:
                    continue

            # retryable
            if r.status_code == 429 or (500 <= r.status_code <= 599):
                if attempt < self.retry.max_retries:
                    self._retry_sleep(attempt, r.headers.get("Retry-After"))
                    continue

            # fail
            try:
                body = r.json()
            except Exception:
                body = {"message": r.text}

            last_err = GitHubAPIError(
                r.status_code,
                body.get("message", "GitHub API error"),
                details={"debug": debug, "body": body},
            )
            break

        if last_err:
            raise last_err
        raise GitHubAPIError(500, "GitHub request failed (unknown)", {})

    def _paginate(
        self,
        *,
        url: str,
        params: Dict[str, Any],
        per_page: int,
        max_pages: int,
        max_items: Optional[int],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        per_page = max(1, min(int(per_page), 100))
        max_pages = max(1, min(int(max_pages), 50))
        max_items_i = int(max_items) if max_items is not None else None
        if max_items_i is not None:
            max_items_i = max(1, min(max_items_i, 5000))

        out: List[Dict[str, Any]] = []
        pages_fetched = 0
        dbg_last: Dict[str, Any] = {}

        for page in range(1, max_pages + 1):
            pages_fetched += 1
            js, dbg = self._request_json(url, params={**params, "per_page": per_page, "page": page})
            dbg_last = dbg

            if not isinstance(js, list):
                raise GitHubAPIError(500, "Unexpected GitHub response shape (expected list)", {"debug": dbg, "body": js})

            out.extend(js)

            if max_items_i is not None and len(out) >= max_items_i:
                out = out[:max_items_i]
                break

            # stop conditions
            if len(js) == 0:
                break
            if len(js) < per_page:
                break

        debug = {
            "pages_fetched": pages_fetched,
            "items": len(out),
            "per_page": per_page,
            "max_pages": max_pages,
            "max_items": max_items_i,
            "last_page_debug": dbg_last,
        }
        return out, debug

    def list_releases(
        self,
        owner: str,
        repo: str,
        *,
        per_page: int = 20,
        max_pages: int = 5,
        max_items: Optional[int] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        url = f"{self.base}/repos/{owner}/{repo}/releases"
        return self._paginate(url=url, params={}, per_page=per_page, max_pages=max_pages, max_items=max_items)

    def list_pull_requests(
        self,
        owner: str,
        repo: str,
        *,
        state: str = "all",
        per_page: int = 30,
        max_pages: int = 5,
        max_items: Optional[int] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        url = f"{self.base}/repos/{owner}/{repo}/pulls"
        # preserve your existing sort behavior
        params = {"state": state, "sort": "updated"}
        return self._paginate(url=url, params=params, per_page=per_page, max_pages=max_pages, max_items=max_items)

    def list_issues(
        self,
        owner: str,
        repo: str,
        *,
        state: str = "all",
        per_page: int = 50,
        max_pages: int = 5,
        max_items: Optional[int] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        GitHub issues API returns BOTH issues and PRs. Filter PRs out at ingestion time.
        """
        url = f"{self.base}/repos/{owner}/{repo}/issues"
        params = {"state": state, "sort": "updated", "direction": "desc"}
        return self._paginate(url=url, params=params, per_page=per_page, max_pages=max_pages, max_items=max_items)