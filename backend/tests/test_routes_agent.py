import json
from types import SimpleNamespace

from fantasy_agent.agent import core as agent_core
from fantasy_agent.config import settings


class FakeMessageItem:
    type = "message"


class FakeFunctionCallItem:
    type = "function_call"

    def __init__(self, name: str, arguments: dict, call_id: str = "call_1") -> None:
        self.name = name
        self.arguments = json.dumps(arguments)
        self.call_id = call_id


class FakeUsage:
    def __init__(self, input_tokens=10, output_tokens=5, cached_tokens=0) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.input_tokens_details = SimpleNamespace(cached_tokens=cached_tokens)


class FakeResponse:
    def __init__(self, output: list, output_text: str = "") -> None:
        self.output = output
        self.output_text = output_text
        self.usage = FakeUsage()


class FakeResponses:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append({**kwargs, "input": list(kwargs["input"])})
        return self._responses.pop(0)


class FakeOpenAIClient:
    def __init__(self, responses: list[FakeResponse], **_kwargs) -> None:
        self.responses = FakeResponses(responses)


def _patch_openai(monkeypatch, responses: list[FakeResponse]) -> FakeOpenAIClient:
    client = FakeOpenAIClient(responses)
    monkeypatch.setattr(agent_core, "OpenAI", lambda **_kwargs: client)
    return client


def test_ask_requires_api_key(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", None)
    resp = client.post("/api/agent/ask", json={"question": "who should I keep?"})
    assert resp.status_code == 503


def test_ask_returns_answer_steps_and_usage(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setitem(agent_core.TOOL_HANDLERS, "get_league_info", lambda session, **kw: {"name": "Test League"})
    responses = [
        FakeResponse([FakeFunctionCallItem("get_league_info", {})], output_text=""),
        FakeResponse([FakeMessageItem()], output_text="Here's your answer."),
    ]
    _patch_openai(monkeypatch, responses)

    resp = client.post("/api/agent/ask", json={"question": "what are the league rules?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "Here's your answer."
    assert len(body["steps"]) == 1
    assert body["steps"][0]["tool_name"] == "get_league_info"
    assert body["steps"][0]["error"] is False
    assert body["usage"]["input_tokens"] == 20
    assert body["usage"]["output_tokens"] == 10


def test_ask_passes_history_as_plain_text(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    fake_client = _patch_openai(monkeypatch, [FakeResponse([], output_text="follow-up")])

    resp = client.post(
        "/api/agent/ask",
        json={
            "question": "what about my other RB?",
            "history": [
                {"role": "user", "content": "should I keep Bijan?"},
                {"role": "assistant", "content": "Yes, keep him."},
            ],
        },
    )
    assert resp.status_code == 200
    assert fake_client.responses.calls[0]["input"] == [
        {"role": "user", "content": "should I keep Bijan?"},
        {"role": "assistant", "content": "Yes, keep him."},
        {"role": "user", "content": "what about my other RB?"},
    ]


def test_ask_rejects_question_over_1000_chars(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    resp = client.post("/api/agent/ask", json={"question": "x" * 1001})
    assert resp.status_code == 422


def test_ask_caps_history_at_last_10_turns(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    fake_client = _patch_openai(monkeypatch, [FakeResponse([], output_text="ok")])

    history = [{"role": "user", "content": f"turn {i}"} for i in range(15)]
    resp = client.post("/api/agent/ask", json={"question": "final question", "history": history})
    assert resp.status_code == 200

    sent_input = fake_client.responses.calls[0]["input"]
    assert len(sent_input) == 11  # last 10 history turns + the new question
    assert sent_input[0]["content"] == "turn 5"
    assert sent_input[-1]["content"] == "final question"


def test_ask_requires_access_code_when_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "demo_access_code", "letmein")
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    try:
        resp = client.post("/api/agent/ask", json={"question": "hi"})
        assert resp.status_code == 403

        _patch_openai(monkeypatch, [FakeResponse([], output_text="ok")])
        resp = client.post(
            "/api/agent/ask", json={"question": "hi"}, headers={"X-Access-Code": "letmein"}
        )
        assert resp.status_code == 200
    finally:
        monkeypatch.setattr(settings, "demo_access_code", None)
