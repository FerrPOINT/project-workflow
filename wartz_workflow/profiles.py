"""Agent Profile Registry — мост между YAML-схемой и Hermes profiles."""

from __future__ import annotations

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
        line_text = line.strip()
        if line_text.startswith("**Name:**"):
            name = line_text.replace("**Name:**", "").strip()
        elif line_text.startswith("**Role:**") or line_text.startswith("- **Role:**"):
            role = line_text.split("**Role:**", 1)[1].strip() if "**Role:**" in line_text else ""
        elif line_text.startswith("**Version:**") or line_text.startswith("- **Version:**"):
            version = line_text.split("**Version:**", 1)[1].strip() if "**Version:**" in line_text else ""
        elif "Oath:" in line_text or "манифест" in line_text.lower() or "клятва" in line_text.lower():
            oath = line_text.split("«", 1)[1].split("»", 1)[0] if "«" in line_text else line_text

        # Phase references
        if "Phase " in line_text:
            import re
            found = re.findall(r"Phase\s+(\d+(?:\.\d+)?[a-zA-Z.]?)", line_text)
            phases.extend(found)

        # MUST / MUST NOT sections
        if line_text.startswith("## What You MUST NOT") or line_text.startswith("### MUST NOT"):
            in_must_not = True
            in_must = False
            continue
        if line_text.startswith("## What You MUST") or line_text.startswith("### MUST"):
            in_must = True
            in_must_not = False
            continue
        if line_text.startswith("##") or line_text.startswith("# "):
            in_must_not = False
            in_must = False
            continue

        if in_must_not and line_text.startswith("- ❌"):
            must_not.append(line_text.replace("- ❌", "").strip())
        if in_must and line_text.startswith("- ✅"):
            must.append(line_text.replace("- ✅", "").strip())

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


def build_delegate_payload(phase_code: str, task_key: str, task_id: str, title: str) -> Optional[Dict[str, any]]:
    """Собрать полный payload для delegate_task из профиля агента."""
    from .schema import get_phase

    ph = get_phase(phase_code)
    if not ph:
        return None

    agent = get_agent_for_phase(phase_code)
    if not agent:
        return None

    # Determine toolsets per agent type (hardcoded from legacy phases.yaml)
    toolsets_map = {
        "wartzresearcher": ["search", "browser"],
        "wartzcritic":       ["review"],
        "wartzreviewer":     ["review"],
        "wartzops":          ["jira", "gitlab"],
        "wartzcoder":        ["terminal", "file"],
    }

    toolsets = toolsets_map.get(agent.name, [])

    prompt = f"Phase {phase_code} for {task_key}: {title}"
    prompt = prompt.replace("{task_key}", task_key)
    prompt = prompt.replace("{task_id}", task_id)
    prompt = prompt.replace("{title}", title)
    prompt = prompt.replace("{phase_code}", phase_code)

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
        "role": "leaf",
        "goal": prompt[:80],
        "context": context,
        "toolsets": toolsets,
        "timeout_min": ph.delegate.timeout_min if ph.delegate else 10,
    }
