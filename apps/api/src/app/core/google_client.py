from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import time
import random
import requests
from io import BytesIO

from docx import Document as DocxDocument  # python-docx

from app.core.config import settings


class GoogleAPIError(RuntimeError):
    def __init__(self, status_code: int, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details or {}


class GoogleClient:
    """
    V1.5:
      - Add retry/backoff for Drive calls (429 + 5xx)
      - OAuth refresh remains strict (don't hide broken creds)
    """

    GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
    DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    def __init__(
        self,
        *,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        refresh_token: Optional[str] = None,
        timeout_s: int = 60,
        max_retries: int = 5,
    ):
        self.client_id = client_id or settings.GOOGLE_CLIENT_ID
        self.client_secret = client_secret or settings.GOOGLE_CLIENT_SECRET
        self.refresh_token = refresh_token or settings.GOOGLE_REFRESH_TOKEN

        if not self.client_id or not self.client_secret or not self.refresh_token:
            raise GoogleAPIError(
                401,
                "Google OAuth creds missing (client_id/client_secret/refresh_token). "
                "Provide via connector.config or env vars GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET/GOOGLE_REFRESH_TOKEN.",
            )

        self._access_token: Optional[str] = None
        self._access_token_exp: float = 0.0

        self.drive_base = "https://www.googleapis.com/drive/v3"
        self.oauth_token_url = "https://oauth2.googleapis.com/token"

        self.timeout_s = int(timeout_s)
        self.max_retries = max(1, min(int(max_retries), 8))

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "pm-agent-os/1.0"})

    def _refresh_access_token(self) -> str:
        now = time.time()
        if self._access_token and now < (self._access_token_exp - 30):
            return self._access_token

        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
        }
        r = self.session.post(self.oauth_token_url, data=data, timeout=30)
        if r.status_code >= 400:
            try:
                body = r.json()
            except Exception:
                body = {"message": r.text}
            raise GoogleAPIError(r.status_code, "OAuth token refresh failed", {"body": body})

        js = r.json()
        token = js.get("access_token")
        expires_in = int(js.get("expires_in", 3600))
        if not token:
            raise GoogleAPIError(500, "OAuth token refresh returned no access_token", {"body": js})

        self._access_token = token
        self._access_token_exp = now + expires_in
        return token

    def _headers(self) -> Dict[str, str]:
        tok = self._refresh_access_token()
        return {"Authorization": f"Bearer {tok}"}

    def _sleep(self, attempt: int, retry_after: Optional[str] = None) -> float:
        if retry_after:
            try:
                s = float(retry_after)
                s = max(0.0, min(s, 15.0))
                time.sleep(s)
                return s
            except Exception:
                pass

        base = 0.8 * (2 ** max(0, attempt - 1))
        jitter = random.uniform(0.0, 0.25 * base)
        s = min(12.0, base + jitter)
        time.sleep(s)
        return s

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        last_err: Optional[GoogleAPIError] = None
        for attempt in range(1, self.max_retries + 1):
            r = self.session.request(method, url, headers=headers, params=params, timeout=self.timeout_s)

            if 200 <= r.status_code < 300:
                return r

            if r.status_code == 429 or (500 <= r.status_code <= 599):
                if attempt < self.max_retries:
                    self._sleep(attempt, r.headers.get("Retry-After"))
                    continue

            try:
                body = r.json()
            except Exception:
                body = {"message": r.text}

            last_err = GoogleAPIError(
                r.status_code,
                "Google API request failed",
                {"url": url, "params": params or {}, "body": body, "status_code": r.status_code},
            )
            break

        if last_err:
            raise last_err
        raise GoogleAPIError(500, "Google API request failed (unknown error)")

    def list_docs_in_folder(
        self,
        *,
        folder_id: str,
        page_size: int = 100,
        page_token: Optional[str] = None,
        include_docx: bool = True,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        mime_q_parts = [f"mimeType='{self.GOOGLE_DOC_MIME}'"]
        if include_docx:
            mime_q_parts.append(f"mimeType='{self.DOCX_MIME}'")

        mime_q = " or ".join(mime_q_parts)
        q = f"'{folder_id}' in parents and ({mime_q}) and trashed=false"

        params: Dict[str, Any] = {
            "q": q,
            "pageSize": max(1, min(int(page_size), 1000)),
            "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,createdTime,owners(emailAddress),webViewLink)",
        }
        if page_token:
            params["pageToken"] = page_token

        url = f"{self.drive_base}/files"
        r = self._request("GET", url, headers=self._headers(), params=params)

        js = r.json()
        files = js.get("files") or []
        next_token = js.get("nextPageToken")
        return files, {"nextPageToken": next_token, "count": len(files), "q": q}

    def export_google_doc_text(self, *, file_id: str) -> Tuple[str, Dict[str, Any]]:
        url = f"{self.drive_base}/files/{file_id}/export"
        params = {"mimeType": "text/plain"}
        r = self._request("GET", url, headers=self._headers(), params=params)
        return r.text or "", {"status_code": r.status_code}

    def download_file_bytes(self, *, file_id: str) -> Tuple[bytes, Dict[str, Any]]:
        url = f"{self.drive_base}/files/{file_id}"
        params = {"alt": "media"}
        r = self._request("GET", url, headers=self._headers(), params=params)
        return r.content or b"", {"status_code": r.status_code}

    def extract_text_from_docx_bytes(self, data: bytes) -> str:
        if not data:
            return ""
        doc = DocxDocument(BytesIO(data))
        paras = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
        return "\n".join(paras).strip()