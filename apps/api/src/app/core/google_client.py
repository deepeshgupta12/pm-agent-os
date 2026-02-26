from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import time
import requests

from app.core.config import settings


class GoogleAPIError(RuntimeError):
    def __init__(self, status_code: int, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details or {}


class GoogleClient:
    """
    Minimal Google client for V1:
      - list Google Docs in a Drive folder
      - export a Google Doc to text/plain

    Auth: OAuth refresh_token flow. Uses:
      - client_id, client_secret, refresh_token
    """

    def __init__(
        self,
        *,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        refresh_token: Optional[str] = None,
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
        r = requests.post(self.oauth_token_url, data=data, timeout=30)
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

    def list_google_docs_in_folder(
        self,
        *,
        folder_id: str,
        page_size: int = 100,
        page_token: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Returns Drive files that are Google Docs inside folder.
        """
        q = f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.document' and trashed=false"
        params: Dict[str, Any] = {
            "q": q,
            "pageSize": max(1, min(int(page_size), 1000)),
            "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,createdTime,owners(emailAddress),webViewLink)",
        }
        if page_token:
            params["pageToken"] = page_token

        url = f"{self.drive_base}/files"
        r = requests.get(url, headers=self._headers(), params=params, timeout=45)

        debug = {"status_code": r.status_code}
        if r.status_code >= 400:
            try:
                body = r.json()
            except Exception:
                body = {"message": r.text}
            raise GoogleAPIError(r.status_code, "Drive files.list failed", {"debug": debug, "body": body})

        js = r.json()
        files = js.get("files") or []
        next_token = js.get("nextPageToken")
        return files, {"nextPageToken": next_token, "count": len(files)}

    def export_doc_text(self, *, file_id: str) -> Tuple[str, Dict[str, Any]]:
        """
        Drive export: GET /files/{fileId}/export?mimeType=text/plain
        Works for Google Docs.
        """
        url = f"{self.drive_base}/files/{file_id}/export"
        params = {"mimeType": "text/plain"}
        r = requests.get(url, headers=self._headers(), params=params, timeout=60)

        debug = {"status_code": r.status_code}
        if r.status_code >= 400:
            # export errors are sometimes plain text
            try:
                body = r.json()
            except Exception:
                body = {"message": r.text}
            raise GoogleAPIError(r.status_code, "Drive files.export failed", {"debug": debug, "body": body})

        # text/plain
        return r.text or "", debug