"""Provider protocol, usage ledger, bounded failures and credential isolation."""

import copy
import json
import sqlite3

import httpx
import pytest

from sabermetrics.config import settings
from sabermetrics.errors import FatalError, LLMCostCeilingExceeded, RecoverableError
from sabermetrics.reasoning.client import ModelClient, cost_attribution
from scripts.setup_db import setup_database


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / "calls.db"
    setup_database(path)
    monkeypatch.setenv("HF_TOKEN", "private-test-key")
    result = ModelClient(path)
    yield result
    result._client.close()


def body(finish="stop", content='{"ok":true}'):
    return {
        "id": "request-1",
        "choices": [
            {
                "finish_reason": finish,
                "message": {"content": content, "reasoning_content": "not user-facing"},
            }
        ],
        "usage": {
            "prompt_tokens": 1000,
            "prompt_tokens_details": {"cached_tokens": 600},
            "completion_tokens": 200,
        },
    }


def mock(client, handler):
    client._client.close()
    client._client = httpx.Client(
        base_url="https://router.huggingface.co/v1",
        headers={"Authorization": "Bearer private-test-key"},
        transport=httpx.MockTransport(handler),
    )


def call(client):
    return client.call_with_cache(
        model="deepseek-ai/DeepSeek-V4-Flash-0731:deepinfra",
        system="Return JSON",
        messages=[{"role": "user", "content": "test"}],
        call_type="vet",
    )


def test_protocol_caching_and_cost_attribution(client):
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "Card facts",
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        }
    ]
    before = copy.deepcopy(messages)

    def handler(request):
        assert str(request.url) == "https://router.huggingface.co/v1/chat/completions"
        payload = json.loads(request.content)
        assert payload["model"] == "deepseek-ai/DeepSeek-V4-Flash-0731:deepinfra"
        assert payload["reasoning_effort"] == "none"
        assert payload["messages"][1]["content"] == "Card facts"
        assert payload["max_tokens"] == 4000
        return httpx.Response(200, json=body())

    mock(client, handler)
    with cost_attribution("owner", "deck"):
        result = client.call_with_cache(
            "deepseek-ai/DeepSeek-V4-Flash-0731:deepinfra",
            "Return JSON",
            messages,
            cache_breakpoints=[0],
        )
    assert messages == before
    assert result.content == '{"ok":true}'
    assert result.cost_usd == pytest.approx(
        (400 * 0.06 + 600 * 0.015 + 200 * 0.18) / 1_000_000
    )
    with sqlite3.connect(client.db_path) as conn:
        row = conn.execute(
            "SELECT user_id,deck_id,model,input_tokens,cached_input_tokens,output_tokens FROM cost_log"
        ).fetchone()
    assert row == (
        "owner",
        "deck",
        "deepseek-ai/DeepSeek-V4-Flash-0731:deepinfra",
        1000,
        600,
        200,
    )


def test_ceiling_stops_call_before_network(client, monkeypatch):
    monkeypatch.setattr(
        client, "get_monthly_spend", lambda: settings.llm.monthly_cost_ceiling_usd
    )
    mock(client, lambda _: pytest.fail("Network must not be reached"))
    with pytest.raises(LLMCostCeilingExceeded):
        call(client)


@pytest.mark.parametrize("status", [401, 402, 403, 400])
def test_fatal_errors_do_not_retry_or_expose_provider_body(client, monkeypatch, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status, json={"error": "private-test-key and prompt contents"}
        )

    mock(client, handler)
    monkeypatch.setattr(
        "sabermetrics.reasoning.client.time.sleep",
        lambda _: pytest.fail("Must not retry"),
    )
    with pytest.raises(FatalError) as error:
        call(client)
    assert "private-test-key" not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_failures_retry_at_most_three_times(client, monkeypatch, status):
    calls = []
    sleeps = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status)

    mock(client, handler)
    monkeypatch.setattr("sabermetrics.reasoning.client.time.sleep", sleeps.append)
    with pytest.raises(RecoverableError):
        call(client)
    assert len(calls) == 3 and sleeps == [2, 4]


@pytest.mark.parametrize(
    "finish,content",
    [("length", '{"truncated":'), ("stop", ""), ("content_filter", None)],
)
def test_unusable_answers_still_record_billable_usage(client, finish, content):
    mock(client, lambda _: httpx.Response(200, json=body(finish, content)))
    with pytest.raises(RecoverableError):
        call(client)
    with sqlite3.connect(client.db_path) as conn:
        assert conn.execute("SELECT count(*) FROM cost_log").fetchone()[0] == 1


def test_missing_usage_is_not_silently_zero_cost(client):
    mock(client, lambda _: httpx.Response(200, json={"choices": body()["choices"]}))
    with pytest.raises(FatalError, match="usage"):
        call(client)


def test_hf_key_required_and_no_other_provider_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-be-used")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "must-not-be-used")
    with pytest.raises(FatalError, match="HF_TOKEN"):
        ModelClient(tmp_path / "unused.db")


def test_client_pins_hugging_face_origin_and_does_not_follow_redirects(client):
    assert str(client._client.base_url) == "https://router.huggingface.co/v1/"
    assert client._client.headers["Authorization"] == "Bearer private-test-key"
    assert client._client.follow_redirects is False


def test_absent_cache_counter_bills_all_input_at_standard_rate(client):
    response = body()
    response["usage"].pop("prompt_tokens_details")
    mock(client, lambda _: httpx.Response(200, json=response))
    result = call(client)
    assert result.cached_input_tokens == 0
    assert result.cost_usd == pytest.approx((1000 * 0.06 + 200 * 0.18) / 1_000_000)
