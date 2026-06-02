"""GitLab adapter — concrete implementation of GitLabPort."""

from __future__ import annotations

import os
from typing import Optional, Tuple

import requests

from ...adapters.ports import GitLabPort
from ...config import GITLAB_API_URL, GITLAB_PROJECT_ID


class GitLabAdapter(GitLabPort):
    """Production GitLab adapter via REST API."""

    def __init__(self, api_url: str = GITLAB_API_URL, project_id: str = GITLAB_PROJECT_ID) -> None:
        self.api_url = api_url
        self.project_id = project_id
        self._token = os.environ.get("GLAB_TOKEN", "")

    def _request(self, path: str) -> Tuple[bool, dict]:
        if not self._token:
            return False, {"error": "GLAB_TOKEN не задан"}

        url = f"{self.api_url}{path}"
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code >= 400:
                return False, {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
            return True, r.json()
        except requests.RequestException as e:
            return False, {"error": str(e)}

    def get_merge_request(self, project_id: str, mr_iid: int) -> Optional[dict]:
        ok, data = self._request(f"/projects/{project_id}/merge_requests/{mr_iid}")
        return data if ok else None

    def get_project(self, project_id: str) -> Optional[dict]:
        ok, data = self._request(f"/projects/{project_id}")
        return data if ok else None

    def ping(self) -> Tuple[bool, str]:
        if not self._token:
            return False, "GLAB_TOKEN не задан"
        ok, data = self._request("/user")
        if ok:
            username = data.get("username", "unknown") if isinstance(data, dict) else "unknown"
            return True, f"GitLab OK ({username})"
        return False, str(data)
