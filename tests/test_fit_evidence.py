"""Review evidence distinguishes absence of data from observed zero inclusion."""

import json
from types import SimpleNamespace

import pytest

from sabermetrics.reasoning.fit import FitScorer


@pytest.mark.parametrize(
    "variant,expected", [(None, "data unavailable"), ("clones", "0% of observed")]
)
def test_missing_corpus_is_not_zero_inclusion(tmp_path, monkeypatch, variant, expected):
    captured = {}

    def call(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            content=json.dumps(
                [
                    {
                        "name": "Review Card",
                        "fit_score": 7,
                        "reasoning": "Matches the printed effect",
                    }
                ]
            ),
            cost_usd=0.004,
        )

    monkeypatch.setattr(
        "sabermetrics.reasoning.client.AnthropicClient.get_instance",
        lambda *args: SimpleNamespace(call_with_cache=call),
    )
    scorer = FitScorer(tmp_path / "unused.db")
    scorer.score_cards_batch(
        [
            {
                "name": "Review Card",
                "oracle_text": "Draw a card.",
                "_empirical_inclusion": 0.0,
            }
        ],
        "Strategy",
        empirical_variant=variant,
    )
    prompt = captured["messages"][0]["content"]
    assert expected in prompt
    if variant is None:
        assert "0%" not in prompt
    assert "never zero inclusion" in captured["system"]
    assert scorer.last_batch_cost_usd == 0.004
    assert scorer.last_batch_complete


def test_partial_verdicts_are_flagged_and_consumed_cost_retained(tmp_path, monkeypatch):
    fake = SimpleNamespace(
        call_with_cache=lambda **kwargs: SimpleNamespace(
            content='[{"name":"A", "fit_score":8, "reasoning":"ok"}]', cost_usd=0.002
        )
    )
    monkeypatch.setattr(
        "sabermetrics.reasoning.client.AnthropicClient.get_instance", lambda *args: fake
    )
    scorer = FitScorer(tmp_path / "unused.db")
    result = scorer.score_cards_batch([{"name": "A"}, {"name": "B"}], "Strategy")
    assert len(result) == 2
    assert not scorer.last_batch_complete
    assert scorer.last_batch_cost_usd == 0.002
