"""Explicit, scoped experimental factors. Defaults reproduce the prior candidate."""

import math
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Experiment:
    evidence_weight: float = 0.45
    land_evidence_weight: float = 0.0
    land_risk_weight: float = 0.0
    budget_recall: int = 0
    draw_selection: bool = False
    preserve_functions: bool = True

    def __post_init__(self):
        if (
            type(self.draw_selection) is not bool
            or type(self.preserve_functions) is not bool
        ):
            raise ValueError("Draw selection control must be boolean")
        for value in (
            self.evidence_weight,
            self.land_evidence_weight,
            self.land_risk_weight,
        ):
            if not math.isfinite(value):
                raise ValueError("Nonfinite experiment weight")
        if not 0 <= self.evidence_weight <= 0.9:
            raise ValueError("Evidence weight must leave room for synergy")
        if (
            not 0 <= self.land_evidence_weight <= 50
            or not 0 <= self.land_risk_weight <= 5
        ):
            raise ValueError("Land weights outside experimental bounds")
        if type(self.budget_recall) is not int or not 0 <= self.budget_recall <= 24:
            raise ValueError("Recall bound must be an integer in 0..24")

    def to_dict(self):
        return asdict(self)


_BASELINE = Experiment()
_current = ContextVar("selection_experiment", default=_BASELINE)


def current() -> Experiment:
    return _current.get()


def production_policy() -> Experiment:
    """Exact deployed web policy, shared with evaluation rather than re-created."""
    return Experiment(draw_selection=True, preserve_functions=True)


@contextmanager
def using(experiment: Experiment):
    token = _current.set(experiment)
    try:
        yield experiment
    finally:
        _current.reset(token)
