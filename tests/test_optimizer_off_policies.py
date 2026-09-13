import pytest

from sabermetrics.intelligence.experiment import Experiment, current, using
from sabermetrics.pipeline.greedy_optimizer import rebalance_budget, swap_refine
from sabermetrics.pipeline.slot_assigner import SlotAssignment

_VALID = ("current", "off", "preserve")
_INVALID = (
    None,
    True,
    False,
    [],
    ["off"],
    0,
    1,
    {},
    "",
    "OFF",
    "Current",
    "disabled",
    "preserve ",
    b"off",
)


class _Explodes:
    """Raises on any use so off-paths cannot do candidate or objective work."""

    def __iter__(self):
        raise AssertionError("unexpected iteration")

    def __len__(self):
        raise AssertionError("unexpected len")

    def __getitem__(self, key):
        raise AssertionError("unexpected getitem")

    def __getattr__(self, name):
        raise AssertionError(f"unexpected attr {name}")

    def get(self, *args, **kwargs):
        raise AssertionError("unexpected get")


def _deck():
    card = {"name": "Sol Ring", "id": "sr", "type_line": "Artifact", "price_usd": 1.0}
    assignment = SlotAssignment(card=card, slot_role="ramp", score=1.0, alternatives=[])
    return [assignment], assignment, assignment.card


@pytest.mark.parametrize("policy", _VALID)
def test_valid_policy_enums(policy):
    Experiment(swap_policy=policy)
    Experiment(rebalance_policy=policy)
    Experiment(swap_policy=policy, rebalance_policy=policy)


@pytest.mark.parametrize("bad", _INVALID)
def test_invalid_policy_enums_rejected(bad):
    with pytest.raises(ValueError):
        Experiment(swap_policy=bad)
    with pytest.raises(ValueError):
        Experiment(rebalance_policy=bad)


def test_defaults_to_dict_and_context_restoration():
    baseline = Experiment()
    assert baseline.swap_policy == "current"
    assert baseline.rebalance_policy == "current"
    exported = baseline.to_dict()
    assert exported["swap_policy"] == "current"
    assert exported["rebalance_policy"] == "current"
    assert current() == baseline

    off_swap = Experiment(swap_policy="off")
    assert off_swap.to_dict()["swap_policy"] == "off"
    assert off_swap.to_dict()["rebalance_policy"] == "current"

    mixed = Experiment(swap_policy="off", rebalance_policy="preserve")
    assert mixed.to_dict()["swap_policy"] == "off"
    assert mixed.to_dict()["rebalance_policy"] == "preserve"

    with using(Experiment(swap_policy="off")):
        assert current().swap_policy == "off"
        assert current().rebalance_policy == "current"
        with pytest.raises(RuntimeError), using(Experiment(rebalance_policy="off")):
            raise RuntimeError()
        assert current().swap_policy == "off"
        assert current().rebalance_policy == "current"
    assert current() == baseline


def test_swap_off_identity_before_any_work():
    deck, assignment, card = _deck()
    snapshot = dict(card)
    boom = _Explodes()
    with using(Experiment(swap_policy="off")):
        result, n = swap_refine(deck, boom, boom, boom, 40.0)
    assert n == 0
    assert result is deck
    assert result[0] is assignment
    assert result[0].card is card
    assert card == snapshot


def test_rebalance_off_identity_zero_stats_before_any_work():
    deck, assignment, card = _deck()
    snapshot = dict(card)
    boom = _Explodes()
    with using(Experiment(rebalance_policy="off")):
        result, stats = rebalance_budget(deck, boom, boom, boom, 40.0)
    assert result is deck
    assert result[0] is assignment
    assert result[0].card is card
    assert card == snapshot
    assert stats == {
        "upgrades": 0,
        "unbundles": 0,
        "downgrades": 0,
        "spent": 0.0,
        "final_total": 1.0,
        "utilization": 0.025,
    }


def test_current_still_performs_work():
    deck, _, _ = _deck()
    boom = _Explodes()
    with using(Experiment(swap_policy="current")), pytest.raises(AssertionError):
        swap_refine(deck, boom, boom, boom, 40.0)
    with using(Experiment(rebalance_policy="current")), pytest.raises(AssertionError):
        rebalance_budget(deck, boom, boom, boom, 40.0)
