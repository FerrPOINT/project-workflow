"""Интеграция с Jira и GitLab API."""

import os
import subprocess
from typing import Optional, Tuple, Dict, Any

from .config import JIRA_API_URL, GITLAB_API_URL, GITLAB_PROJECT_ID


# ── Jira ────────────────────────────────────────────────────────────────

def get_jira_auth() -> Tuple[str, str]:
    """Получить Jira credentials из env."""
    token = os.environ.get("JIRA_ACCESS_TOKEN") or os.environ.get("JIRA_TOKEN")
    user = os.environ.get("JIRA_USER") or os.environ.get("JIRA_USERNAME")
    return user or "", token or ""


def _jira_request(path: str, method: str = "GET", json_data: Optional[Dict] = None) -> Tuple[bool, Any]:
    """Base Jira API request."""
    import requests

    user, token = get_jira_auth()
    if not token:
        return False, "JIRA_TOKEN не задан"

    url = f"{JIRA_API_URL}{path}"
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


def get_jira_status(issue_key: str) -> Optional[str]:
    """Получить статус Jira тикета."""
    ok, data = _jira_request(f"/issue/{issue_key}?fields=status")
    if ok and isinstance(data, dict):
        status = data.get("fields", {}).get("status", {}).get("name")
        return status
    return None


def get_jira_transitions(issue_key: str) -> list[Dict[str, Any]]:
    """Получить доступные transitions для тикета."""
    ok, data = _jira_request(f"/issue/{issue_key}/transitions")
    if ok and isinstance(data, dict):
        return data.get("transitions", [])
    return []


def transition_jira(issue_key: str, transition_name: str) -> Tuple[bool, str]:
    """Перевести Jira тикет в новый статус по имени transition."""
    transitions = get_jira_transitions(issue_key)
    target_id = None
    for t in transitions:
        if t.get("name") == transition_name:
            target_id = t.get("id")
            break

    if not target_id:
        names = [t.get("name") for t in transitions]
        return False, f"Transition '{transition_name}' не найдена. Доступные: {names}"

    ok, data = _jira_request(
        f"/issue/{issue_key}/transitions",
        method="POST",
        json_data={"transition": {"id": target_id}},
    )
    if ok:
        return True, f"Jira {issue_key} → {transition_name}"
    return False, str(data)


def ping_jira() -> Tuple[bool, str]:
    """Проверить доступность Jira API."""
    user, token = get_jira_auth()
    if not token:
        return False, "JIRA_TOKEN не задан"
    ok, data = _jira_request("/myself")
    if ok:
        display = data.get("displayName", "unknown") if isinstance(data, dict) else "unknown"
        return True, f"Jira API OK ({display})"
    return False, str(data)


# ── GitLab ────────────────────────────────────────────────────────────

def get_gitlab_token() -> str:
    return os.environ.get("GLAB_TOKEN") or os.environ.get("GITLAB_TOKEN") or ""


def _gitlab_request(path: str, method: str = "GET", json_data: Optional[Dict] = None) -> Tuple[bool, Any]:
    """Base GitLab API request."""
    import requests

    token = get_gitlab_token()
    if not token:
        return False, "GLAB_TOKEN не задан"

    url = f"{GITLAB_API_URL}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        if method == "GET":
            r = requests.get(url, headers=headers, timeout=15)
        elif method == "POST":
            r = requests.post(url, headers=headers, json=json_data, timeout=15)
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


def get_mr_state(task_id: str) -> Optional[Dict[str, Any]]:
    """Найти MR по task_id в title/description/source_branch."""
    token = get_gitlab_token()
    if not token:
        return None

    # Search by source branch containing task_id
    ok, data = _gitlab_request(
        f"/projects/{GITLAB_PROJECT_ID}/merge_requests?state=all&search={task_id}"
    )
    if ok and isinstance(data, list) and data:
        mr = data[0]
        return {
            "iid": mr.get("iid"),
            "title": mr.get("title"),
            "state": mr.get("state"),
            "merged_by": mr.get("merged_by", {}).get("username") if mr.get("merged_by") else None,
            "web_url": mr.get("web_url"),
            "source_branch": mr.get("source_branch"),
            "target_branch": mr.get("target_branch"),
        }
    return None


def ping_gitlab() -> Tuple[bool, str]:
    """Проверить доступность GitLab API."""
    token = get_gitlab_token()
    if not token:
        return False, "GLAB_TOKEN не задан"
    ok, data = _gitlab_request("/user")
    if ok:
        username = data.get("username", "unknown") if isinstance(data, dict) else "unknown"
        return True, f"GitLab API OK ({username})"
    return False, str(data)
