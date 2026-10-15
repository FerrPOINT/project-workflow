"""Canonical dependency-free platform namespace contracts, also exportable to SSR consumers."""
import os
from collections.abc import Mapping

PAT_PREFIXES = ("sdlc_pat_", "pdlc_pat_")


def is_personal_token(value: str) -> bool:
    """Prefix dispatch only: the issuer must still authenticate the credential."""
    return value.startswith(PAT_PREFIXES)


def platform_env(suffix: str, environment: Mapping[str, str] | None = None) -> str | None:
    values = os.environ if environment is None else environment
    canonical, legacy = values.get("PDLC_" + suffix), values.get("SDLC_" + suffix)
    if canonical is not None and legacy is not None and canonical != legacy:
        raise ValueError("conflicting PDLC/SDLC environment aliases: " + suffix)
    return canonical if canonical is not None else legacy
