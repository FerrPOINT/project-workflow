"""Phase Finite State Machine using transitions library.

Formalizes the lifecycle of a single workflow phase:
    in_progress → done
    in_progress → blocked
    in_progress → rollback
    in_progress → delegated
"""

from __future__ import annotations

import logging
from typing import Any

from transitions import Machine
from transitions.core import MachineError

logger = logging.getLogger(__name__)


class _FSMModel:
    """Dummy model for transitions Machine."""

    state: str = "pending"


class PhaseFSM:
    """Formalized phase lifecycle state machine."""

    STATES = ["pending", "in_progress", "done", "blocked", "rollback", "delegated"]

    TRANSITIONS: list[dict[str, Any]] = [
        {"trigger": "succeed", "source": "in_progress", "dest": "done"},
        {"trigger": "partial_pass", "source": "in_progress", "dest": "in_progress"},
        {"trigger": "soft_fail", "source": "in_progress", "dest": "in_progress"},
        {"trigger": "hard_fail", "source": "in_progress", "dest": "in_progress"},
        {"trigger": "block", "source": "in_progress", "dest": "blocked"},
        {"trigger": "rollback", "source": "in_progress", "dest": "rollback"},
        {"trigger": "delegate", "source": "in_progress", "dest": "delegated"},
    ]

    VERDICT_TO_TRIGGER: dict[str, str] = {
        "pass": "succeed",
        "partial": "partial_pass",
        "soft_fail": "soft_fail",
        "hard_fail": "hard_fail",
        "blocked": "block",
        "rollback": "rollback",
        "delegate": "delegate",
    }

    def __init__(self, initial: str = "in_progress"):
        self._model = _FSMModel()
        self._model.state = initial
        self._machine: Any = Machine(
            model=self._model,
            states=self.STATES,
            initial=initial,
            transitions=self.TRANSITIONS,
            send_event=False,
        )

    @property
    def state(self) -> str:
        return self._model.state

    def apply_verdict(self, verdict: str) -> str:
        """Apply a wizard verdict and return the new state."""
        trigger = self.VERDICT_TO_TRIGGER.get(verdict)
        if trigger is None:
            return self.state
        try:
            getattr(self._model, trigger)()
        except MachineError as exc:
            logger.warning("FSM transition rejected: %s", exc)
        return self.state
