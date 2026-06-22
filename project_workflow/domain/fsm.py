"""Phase Finite State Machine using transitions library.

Formalizes the lifecycle of a single workflow phase:
    pending → in_progress → done
                ↘ blocked
                ↘ rollback
                ↘ delegated
"""
from transitions import Machine


class _FSMModel:
    """Dummy model for transitions Machine."""
    pass


class PhaseFSM:
    """Formalized phase lifecycle state machine."""

    STATES = ["pending", "in_progress", "done", "blocked", "rollback", "delegated"]

    TRANSITIONS = [
        {"trigger": "start", "source": "pending", "dest": "in_progress"},
        {"trigger": "succeed", "source": "in_progress", "dest": "done"},
        {"trigger": "partial_pass", "source": "in_progress", "dest": "in_progress"},
        {"trigger": "block", "source": "in_progress", "dest": "blocked"},
        {"trigger": "rollback", "source": "in_progress", "dest": "rollback"},
        {"trigger": "delegate", "source": "in_progress", "dest": "delegated"},
        {"trigger": "restart", "source": ["blocked", "rollback", "delegated"], "dest": "pending"},
        {"trigger": "resume", "source": ["blocked", "rollback", "delegated"], "dest": "in_progress"},
    ]

    VERDICT_TO_TRIGGER = {
        "pass": "succeed",
        "partial": "partial_pass",
        "blocked": "block",
        "rollback": "rollback",
        "delegate": "delegate",
    }

    def __init__(self, initial: str = "in_progress"):
        self._model = _FSMModel()
        self._model.state = initial
        self._machine = Machine(
            model=self._model,
            states=self.STATES,
            initial=initial,
            transitions=self.TRANSITIONS,
            send_event=False,
        )

    @property
    def state(self) -> str:
        return self._model.state

    def is_terminal(self) -> bool:
        return self.state in {"done", "blocked"}

    def apply_verdict(self, verdict: str) -> str:
        """Apply a wizard verdict and return the new state."""
        trigger = self.VERDICT_TO_TRIGGER.get(verdict)
        if trigger is None:
            return self.state
        try:
            getattr(self._model, trigger)()
        except Exception:
            pass
        return self.state
