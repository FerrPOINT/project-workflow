"""Agent Profile Registry — мост между YAML-схемой и Hermes profiles."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class AgentProfile:
    """Описание агента из SOUL.md + override из agent-map.yml."""
    name: str                          # wartzresearcher, wartzreviewer, etc.
    profile_dir: Path                  # /root/.hermes/profiles/{name}
    soul_path: Path                    # .../SOUL.md
    role: str = ""
    version: str = ""
    phases: List[str] = field(default_factory=list)   # фазы которые выполняет
    toolsets: List[str] = field(default_factory=list)
    auto_load_skills: List[str] = field(default_factory=list)
    oath: str = ""                     # ключевая клятва/манифест
    must_not: List[str] = field(default_factory=list)  # запреты
    must: List[str] = field(default_factory=list)      # обязанности
    is_available: bool = False


def parse_soul_md(path: Path) -> Optional[AgentProfile]:
    """Прочитать SOUL.md и извлечь метаданные агента."""
    if not path.exists():
        return None

    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()

    name = path.parent.name
    role = ""
    version = ""
    oath = ""
    must_not: List[str] = []
    must: List[str] = []
    phases: List[str] = []

    in_must_not = False
    in_must = False

    for line in lines[:150]:  # frontmatter + intro usually within 150 lines
        l = line.strip()
        if l.startswith("**Name:**"):
            name = l.replace("**Name:**", "").strip()
        elif l.startswith("**Role:**") or l.startswith("- **Role:**"):
            role = l.split("**Role:**", 1)[1].strip() if "**Role:**" in l else ""
        elif l.startswith("**Version:**") or l.startswith("- **Version:**"):
            version = l.split("**Version:**", 1)[1].strip() if "**Version:**" in l else ""
        elif "Oath:" in l or "манифест" in l.lower() or "клятва" in l.lower():
            oath = l.split("«", 1)[1].split("»", 1)[0] if "«" in l else l

        # Phase references
        if "Phase " in l:
            import re
            found = re.findall(r"Phase\s+(\d+(?:\.\d+)?[a-zA-Z.]?)", l)
            phases.extend(found)

        # MUST / MUST NOT sections
        if l.startswith("## What You MUST NOT") or l.startswith("### MUST NOT"):
            in_must_not = True
            in_must = False
            continue
        if l.startswith("## What You MUST") or l.startswith("### MUST"):
            in_must = True
            in_must_not = False
            continue
        if l.startswith("##") or l.startswith("# "):
            in_must_not = False
            in_must = False
            continue

        if in_must_not and l.startswith("- ❌"):
            must_not.append(l.replace("- ❌", "").strip())
        if in_must and l.startswith("- ✅"):
            must.append(l.replace("- ✅", "").strip())

    # Deduplicate phases
    phases = list(dict.fromkeys(phases))

    return AgentProfile(
        name=name,
        profile_dir=path.parent,
        soul_path=path,
        role=role,
        version=version,
        phases=phases,
        oath=oath,
        must_not=must_not,
        must=must,
        is_available=True,
    )


def load_all_profiles(base_dir: Optional[Path] = None) -> Dict[str, AgentProfile]:
    """Загрузить все доступные профили."""
    base = base_dir or Path("/root/.hermes/profiles")
    profiles: Dict[str, AgentProfile] = {}

    for profile_dir in base.iterdir():
        if not profile_dir.is_dir():
            continue
        soul = profile_dir / "SOUL.md"
        if not soul.exists():
            continue
        agent = parse_soul_md(soul)
        if agent:
            profiles[agent.name] = agent

    return profiles


def get_agent_for_phase(phase_id: str, profiles: Optional[Dict[str, AgentProfile]] = None) -> Optional[AgentProfile]:
    """Найти агента по фазе."""
    # Hardcoded mapping from workflow skill
    phase_agent_map = {
        "0.6": "wartzresearcher",
        "1.5": "wartzresearcher",
        "2": "wartzresearcher",
        "0.9": "wartzcritic",
        "3.5": "wartzcritic",
        "4.5": "wartzcritic",
        "7.5": "wartzreviewer",
        "7.6": "wartzreviewer",
        "7.6.R": "wartzresearcher",
        "7.7": "wartzcritic",
        "8": "wartzops",
        "9": "wartzcoder",
        "10": "wartzcoder",
    }

    agent_name = phase_agent_map.get(phase_id)
    if not agent_name:
        return None

    profs = profiles or load_all_profiles()
    return profs.get(agent_name)


def build_delegate_payload(phase_id: str, jira_key: str, task_id: str, title: str) -> Optional[Dict[str, any]]:
    """Собрать полный payload для delegate_task из профиля + YAML-схемы."""
    from .schema import get_phase

    ph = get_phase(phase_id)
    if not ph or not ph.delegate:
        return None

    agent = get_agent_for_phase(phase_id)
    if not agent:
        return None

    # Render prompt
    prompt = ph.delegate.prompt_template
    prompt = prompt.replace("{jira_key}", jira_key)
    prompt = prompt.replace("{task_id}", task_id)
    prompt = prompt.replace("{title}", title)

    # Build context with agent identity
    context = f"""## Agent Identity
You are {agent.name}: {agent.role}
Version: {agent.version}

### Your Oath
«{agent.oath}»

### What You MUST NOT
"""
    for item in agent.must_not[:5]:
        context += f"- ❌ {item}\n"

    context += "\n### What You MUST\n"
    for item in agent.must[:5]:
        context += f"- ✅ {item}\n"

    context += f"\n## Task Context\n{prompt}\n"

    return {
        "agent": agent.name,
        "role": "leaf",  # delegated agents don't spawn further
        "goal": ph.delegate.prompt_template[:80],
        "context": context,
        "toolsets": ph.delegate.toolsets,
        "timeout_min": ph.delegate.timeout_min,
    }
