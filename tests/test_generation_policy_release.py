from types import SimpleNamespace

import pytest

from sabermetrics.intelligence.experiment import Experiment, current
from sabermetrics.ui.routes import _execute_generation


@pytest.mark.parametrize('fail', [False, True])
def test_web_worker_uses_guarded_policy_and_restores_scope(monkeypatch, tmp_path, fail):
    def build(self, request):
        assert current() == Experiment(draw_selection=True, preserve_functions=True)
        if fail:
            raise RuntimeError('test failure')
        return SimpleNamespace(deck=SimpleNamespace(id=request.deck_id))

    owners = []
    monkeypatch.setattr('sabermetrics.pipeline.deck_builder.DeckBuilder.__init__',
                        lambda self, *args, **kwargs: None)
    monkeypatch.setattr('sabermetrics.pipeline.deck_builder.DeckBuilder.build', build)
    monkeypatch.setattr('sabermetrics.ui.routes.db.DecksRepo',
                        lambda path: SimpleNamespace(set_owner=lambda *args: owners.append(args)))
    captured = dict(db_path=str(tmp_path/'unused.db'), deck_id='deck', commander_id='cmdr',
                    budget_usd=51, power_target=3, strategy=None, user_intent=None,
                    deck_name='Test', owner_id='owner')
    before = current()
    if fail:
        with pytest.raises(RuntimeError, match='test failure'):
            _execute_generation(captured, None)
        assert owners == []
    else:
        assert _execute_generation(captured, None) == 'deck'
        assert owners == [('deck', 'owner')]
    assert current() == before
