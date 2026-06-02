"""Jira adapter — concrete implementation of JiraPort."""

from __future__ import annotations

import os
from typing import Optional, Tuple, Dict, Any

import requests

from ...adapters.ports import JiraPort
from ...config import JIRA_API_URL
from ... import state


class JiraAdapter(JiraPort):
    """Production Jira adapter via REST API."""

    def __init__(self, api_url: str = JIRA_API_URL) -> None:
        self.api_url = api_url

    def _auth(self) -> Tuple[str, str]:
        token = os.environ.get("JIRA_ACCESS_TOKEN") or os.environ.get("JIRA_TOKEN")
        user = os.environ.get("JIRA_USER") or os.environ.get("JIRA_USERNAME")
        return user or "", token or ""

    def _request(self, path: str, method: str = "GET", json_data: Optional[Dict] = None) -> Tuple[bool, Any]:
        user, token = self._auth()
        if not token:
            return False, "JIRA_TOKEN не задан"

        url = f"{self.api_url}{path}"
        auth = (user, token) if user else ("", token)
        headers = {"Content-Type": "application/json", "Accept": "application/json"}

        try:
            if method == "GET":
                r = requests.get(url, auth=auth, headers=headers, timeout=15)
            elif method == "POST":
                r = requests.post(url, auth=auth, headers=headers, json=json_data, timeout=15)
            elif method == "PUT":
                r = requests.put(url, auth=auth, headers=headers, json=json_data, timeout=15)
            else:
                return False, f"Unsupported method: {method}"
        except requests.RequestException as e:
            return False, str(e)

        if r.status_code >= 400:
            return False, f"HTTP {r.status_code}: {r.text[:200]}"

        try:
            return True, r.json()
        except Exception:
            return True, r.text

    def get_status(self, issue_key: str) -> Optional[str]:
        ok, data = self._request(f"/issue/{issue_key}?fields=status")
        if ok and isinstance(data, dict):
            return data.get("fields", {}).get("status", {}).get("name")
        return None

    def get_task_info(self, issue_key: str) -> dict:
        ok, data = self._request(f"/issue/{issue_key}?fields=summary,description,status,assignee")
        if ok and isinstance(data, dict):
            fields = data.get("fields", {})
            return {
                "ok": True,
                "source": "jira",
                "summary": fields.get("summary", ""),
                "description": fields.get("description", ""),
                "status": fields.get("status", {}).get("name", ""),
                "assignee": fields.get("assignee", {}).get("displayName", ""),
                "key": issue_key,
            }
        return {
            "ok": False,
            "source": "empty",
            "summary": "",
            "description": "",
            "status": "",
            "assignee": "",
            "key": issue_key,
            "error": str(data),
        }

    def get_transitions(self, issue_key: str) -> list[Dict[str, Any]]:
        ok, data = self._request(f"/issue/{issue_key}/transitions")
        if ok and isinstance(data, dict):
            return data.get("transitions", [])
        return []

    def transition(self, issue_key: str, transition_name: str) -> Tuple[bool, str]:
        transitions = self.get_transitions(issue_key)
        target_id = None
        for t in transitions:
            if t.get("name") == transition_name:
                target_id = t.get("id")
                break
        if not target_id:
            names = [t.get("name") for t in transitions]
            return False, f"Transition '{transition_name}' не найдена. Доступные: {names}"

        ok, data = self._request(
            f"/issue/{issue_key}/transitions",
            method="POST",
            json_data={"transition": {"id": target_id}},
        )
        if ok:
            return True, f"Jira {issue_key} → {transition_name}"
        return False, str(data)

    def ping(self) -> Tuple[bool, str]:
        user, token = self._auth()
        if not token:
            return False, "JIRA_TOKEN не задан"
        ok, data = self._request("/myself")
        if ok:
            display = data.get("displayName", "unknown") if isinstance(data, dict) else "unknown"
            return True, f"Jira OK ({display})"
        return False, str(data)


