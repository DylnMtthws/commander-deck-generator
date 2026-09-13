"""Integration boundaries: route gates, legacy order, and finite draw budget."""

from pathlib import Path
from types import SimpleNamespace

from sabermetrics.intelligence.experiment import Experiment, using
from sabermetrics.pipeline.generators.draw import DrawPackageGenerator


def test_route_gate_preserves_unknown_and_conditional_candidates(monkeypatch):
    from sabermetrics.intelligence import draw_route_assessment

    observed = []
    statuses = {
        "blocked": "blocked",
        "unknown": "unverified",
        "conditional": "conditional",
    }

    def assess(card, support, commander, power):
        observed.append((support, commander, power))
        return {"status": statuses[card["name"]]}

    monkeypatch.setattr(draw_route_assessment, "assess_draw_routes", assess)
    pool = [
        {"name": n, "price_usd": 1, "type_line": "Instant", "_cvar_score": s}
        for n, s in [("blocked", 1), ("unknown", 0.8), ("conditional", 0.6)]
    ]
    support, commander = [{"name": "Island"}], {"name": "Commander"}
    gen = DrawPackageGenerator(Path(__file__))
    kwargs = {
        "color_identity": ["U"],
        "target_count": 2,
        "budget_remaining": 2,
        "template": SimpleNamespace(unmet_type_targets=lambda _: set()),
        "already_placed": support,
        "role_tag_pool": pool,
        "commander": commander,
    }
    with using(Experiment(draw_package_policy="routes")):
        result = gen.generate(**kwargs)
    assert [a.card["name"] for a in result] == ["unknown", "conditional"]
    assert all(s == support and c == commander and p == 3 for s, c, p in observed)
    assert gen.selection_receipt["spent"] == 2
    with using(Experiment()):
        legacy = gen.generate(**kwargs)
    assert [a.card["name"] for a in legacy] == ["blocked", "unknown"]
    assert not hasattr(gen, "selection_receipt")


def test_routes_zero_budget_does_not_buy_cards(monkeypatch):
    from sabermetrics.intelligence import draw_route_assessment

    monkeypatch.setattr(
        draw_route_assessment, "assess_draw_routes", lambda *a: {"status": "available"}
    )
    gen = DrawPackageGenerator(Path(__file__))
    with using(Experiment(draw_package_policy="routes")):
        result = gen.generate(
            ["U"],
            2,
            0,
            SimpleNamespace(unmet_type_targets=lambda _: set()),
            [],
            [
                {"name": "Paid", "price_usd": 1, "type_line": "Instant"},
                {"name": "Free", "price_usd": 0, "type_line": "Instant"},
            ],
        )
    assert [a.card["name"] for a in result] == ["Free"]
