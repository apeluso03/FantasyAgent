import json
from types import SimpleNamespace

import pytest

from fantasy_agent.agent import core
from fantasy_agent.config import settings


class FakeMessageItem:
    type = "message"

    def __init__(self, text: str) -> None:
        self.text = text


class FakeFunctionCallItem:
    type = "function_call"

    def __init__(self, name: str, arguments: dict, call_id: str = "call_1") -> None:
        self.name = name
        self.arguments = json.dumps(arguments)
        self.call_id = call_id


class FakeUsage:
    def __init__(
        self, input_tokens: int = 10, output_tokens: int = 5, cached_tokens: int = 0
    ) -> None:
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
        # run_agent mutates the same `input_list` object across loop iterations,
        # so snapshot it now -- otherwise every recorded call ends up pointing at
        # whatever the list looks like by the time run_agent() returns.
        snapshot = {**kwargs, "input": list(kwargs["input"])}
        self.calls.append(snapshot)
        return self._responses.pop(0)


class FakeOpenAIClient:
    def __init__(self, responses: list[FakeResponse], **_kwargs) -> None:
        self.responses = FakeResponses(responses)


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "test-key")


def _patch_client(monkeypatch, responses: list[FakeResponse]) -> FakeOpenAIClient:
    client = FakeOpenAIClient(responses)
    monkeypatch.setattr(core, "OpenAI", lambda **_kwargs: client)
    return client


def test_run_agent_returns_text_when_no_tool_use(monkeypatch):
    responses = [FakeResponse([FakeMessageItem("Keep Bijan.")], output_text="Keep Bijan.")]
    _patch_client(monkeypatch, responses)

    answer = core.run_agent("who should I keep?", session=object())

    assert answer == "Keep Bijan."


def test_first_request_passes_instructions_and_tools(monkeypatch):
    responses = [FakeResponse([], output_text="Keep Bijan.")]
    client = _patch_client(monkeypatch, responses)

    core.run_agent("who should I keep?", session=object())

    call = client.responses.calls[0]
    assert call["instructions"] == core.SYSTEM_PROMPT
    assert call["tools"] == core.TOOL_SCHEMAS
    assert call["input"] == [{"role": "user", "content": "who should I keep?"}]


def test_run_agent_executes_tool_and_feeds_result_back(monkeypatch):
    calls = []

    def fake_handler(session, **kwargs):
        calls.append(kwargs)
        return {"ok": True}

    monkeypatch.setitem(core.TOOL_HANDLERS, "get_league_info", fake_handler)

    responses = [
        FakeResponse([FakeFunctionCallItem("get_league_info", {}, call_id="call_1")], output_text=""),
        FakeResponse([FakeMessageItem("Here's your answer.")], output_text="Here's your answer."),
    ]
    client = _patch_client(monkeypatch, responses)

    answer = core.run_agent("what are the league rules?", session=object())

    assert answer == "Here's your answer."
    assert calls == [{}]
    # second request must carry the function's output back, keyed by call_id
    second_call_input = client.responses.calls[1]["input"]
    tool_output_item = second_call_input[-1]
    assert tool_output_item == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": json.dumps({"ok": True}),
    }


def test_run_agent_reports_tool_error_without_crashing(monkeypatch):
    def failing_handler(session, **kwargs):
        raise core.ToolError("no team matches 'Nobody'")

    monkeypatch.setitem(core.TOOL_HANDLERS, "get_roster", failing_handler)

    responses = [
        FakeResponse([FakeFunctionCallItem("get_roster", {"team": "Nobody"})], output_text=""),
        FakeResponse([FakeMessageItem("I couldn't find that team.")], output_text="I couldn't find that team."),
    ]
    client = _patch_client(monkeypatch, responses)

    answer = core.run_agent("show me Nobody's roster", session=object())

    assert answer == "I couldn't find that team."
    tool_output_item = client.responses.calls[1]["input"][-1]
    assert tool_output_item["type"] == "function_call_output"
    assert "Error:" in tool_output_item["output"]
    assert "no team matches" in tool_output_item["output"]


def test_run_agent_reports_unknown_tool_without_crashing(monkeypatch):
    responses = [
        FakeResponse([FakeFunctionCallItem("not_a_real_tool", {})], output_text=""),
        FakeResponse([FakeMessageItem("done")], output_text="done"),
    ]
    _patch_client(monkeypatch, responses)

    answer = core.run_agent("do the impossible", session=object())

    assert answer == "done"


def test_run_agent_stops_after_max_iterations(monkeypatch):
    monkeypatch.setitem(
        core.TOOL_HANDLERS, "get_league_info", lambda session, **kwargs: {"ok": True}
    )
    # Always asks for another tool call -- never returns a final message.
    responses = [
        FakeResponse([FakeFunctionCallItem("get_league_info", {})], output_text="")
        for _ in range(core.MAX_TOOL_ITERATIONS)
    ]
    _patch_client(monkeypatch, responses)

    answer = core.run_agent("infinite question", session=object())

    assert "tool-call limit" in answer


def test_run_agent_requires_api_key(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", None)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        core.run_agent("anything", session=object())


def test_usage_logging_tolerates_missing_cache_details(monkeypatch, caplog):
    """usage.input_tokens_details can be absent on some responses -- logging
    must not crash, just log 0 cached tokens."""
    response = FakeResponse([], output_text="ok")
    response.usage.input_tokens_details = None
    _patch_client(monkeypatch, [response])

    with caplog.at_level("INFO", logger="fantasy_agent.agent.core"):
        answer = core.run_agent("anything", session=object())

    assert answer == "ok"
    assert any("cached=0" in record.message for record in caplog.records)


def test_run_agent_with_trace_records_steps_in_order(monkeypatch):
    def fake_league_info(session, **kwargs):
        return {"name": "Test League"}

    def fake_roster(session, **kwargs):
        raise core.ToolError("no team matches 'Nobody'")

    monkeypatch.setitem(core.TOOL_HANDLERS, "get_league_info", fake_league_info)
    monkeypatch.setitem(core.TOOL_HANDLERS, "get_roster", fake_roster)

    responses = [
        FakeResponse(
            [
                FakeFunctionCallItem("get_league_info", {}, call_id="call_1"),
                FakeFunctionCallItem("get_roster", {"team": "Nobody"}, call_id="call_2"),
            ],
            output_text="",
        ),
        FakeResponse([FakeMessageItem("Here's your answer.")], output_text="Here's your answer."),
    ]
    _patch_client(monkeypatch, responses)

    result = core.run_agent_with_trace("what are the league rules?", session=object())

    assert result.answer == "Here's your answer."
    assert [s.tool_name for s in result.steps] == ["get_league_info", "get_roster"]
    assert result.steps[0].error is False
    assert json.loads(result.steps[0].output_preview) == {"name": "Test League"}
    assert result.steps[1].error is True
    assert "no team matches" in result.steps[1].output_preview
    assert result.usage.input_tokens == 20  # two FakeUsage(input_tokens=10) responses, summed
    assert result.usage.output_tokens == 10


def test_run_agent_with_trace_passes_history_as_plain_text_turns(monkeypatch):
    responses = [FakeResponse([], output_text="follow-up answer")]
    client = _patch_client(monkeypatch, responses)

    history = [
        {"role": "user", "content": "should I keep Bijan?"},
        {"role": "assistant", "content": "Yes, keep him."},
    ]
    result = core.run_agent_with_trace("what about my other RB?", session=object(), history=history)

    assert result.answer == "follow-up answer"
    assert client.responses.calls[0]["input"] == [
        {"role": "user", "content": "should I keep Bijan?"},
        {"role": "assistant", "content": "Yes, keep him."},
        {"role": "user", "content": "what about my other RB?"},
    ]
