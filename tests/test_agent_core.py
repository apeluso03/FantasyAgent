from types import SimpleNamespace

import pytest

from fantasy_agent.agent import core
from fantasy_agent.config import settings


class FakeTextBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class FakeToolUseBlock:
    type = "tool_use"

    def __init__(self, name: str, input: dict, id: str = "tool_1") -> None:
        self.name = name
        self.input = input
        self.id = id


class FakeUsage:
    def __init__(
        self, input_tokens: int = 10, output_tokens: int = 5,
        cache_read_input_tokens: int = 0, cache_creation_input_tokens: int = 0,
    ) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = cache_read_input_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens


class FakeResponse:
    def __init__(self, content: list, stop_reason: str) -> None:
        self.content = content
        self.stop_reason = stop_reason
        self.usage = FakeUsage()


class FakeMessages:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class FakeAnthropicClient:
    def __init__(self, responses: list[FakeResponse], **_kwargs) -> None:
        self.messages = FakeMessages(responses)


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")


def _patch_client(monkeypatch, responses: list[FakeResponse]) -> FakeAnthropicClient:
    client = FakeAnthropicClient(responses)
    monkeypatch.setattr(core.anthropic, "Anthropic", lambda **_kwargs: client)
    return client


def test_run_agent_returns_text_when_no_tool_use(monkeypatch):
    responses = [FakeResponse([FakeTextBlock("Keep Bijan.")], "end_turn")]
    _patch_client(monkeypatch, responses)

    answer = core.run_agent("who should I keep?", session=object())

    assert answer == "Keep Bijan."


def test_run_agent_executes_tool_and_feeds_result_back(monkeypatch):
    calls = []

    def fake_handler(session, **kwargs):
        calls.append(kwargs)
        return {"ok": True}

    monkeypatch.setitem(core.TOOL_HANDLERS, "get_league_info", fake_handler)

    responses = [
        FakeResponse([FakeToolUseBlock("get_league_info", {})], "tool_use"),
        FakeResponse([FakeTextBlock("Here's your answer.")], "end_turn"),
    ]
    client = _patch_client(monkeypatch, responses)

    answer = core.run_agent("what are the league rules?", session=object())

    assert answer == "Here's your answer."
    assert calls == [{}]
    # second request must carry the tool_result back to Claude
    second_call_messages = client.messages.calls[1]["messages"]
    tool_result_message = second_call_messages[-1]
    assert tool_result_message["role"] == "user"
    assert tool_result_message["content"][0]["type"] == "tool_result"
    assert tool_result_message["content"][0]["is_error"] is False


def test_run_agent_reports_tool_error_without_crashing(monkeypatch):
    def failing_handler(session, **kwargs):
        raise core.ToolError("no team matches 'Nobody'")

    monkeypatch.setitem(core.TOOL_HANDLERS, "get_roster", failing_handler)

    responses = [
        FakeResponse([FakeToolUseBlock("get_roster", {"team": "Nobody"})], "tool_use"),
        FakeResponse([FakeTextBlock("I couldn't find that team.")], "end_turn"),
    ]
    client = _patch_client(monkeypatch, responses)

    answer = core.run_agent("show me Nobody's roster", session=object())

    assert answer == "I couldn't find that team."
    tool_result = client.messages.calls[1]["messages"][-1]["content"][0]
    assert tool_result["is_error"] is True
    assert "no team matches" in tool_result["content"]


def test_run_agent_stops_after_max_iterations(monkeypatch):
    monkeypatch.setitem(
        core.TOOL_HANDLERS, "get_league_info", lambda session, **kwargs: {"ok": True}
    )
    # Always asks for another tool call -- never returns end_turn.
    responses = [
        FakeResponse([FakeToolUseBlock("get_league_info", {})], "tool_use")
        for _ in range(core.MAX_TOOL_ITERATIONS)
    ]
    _patch_client(monkeypatch, responses)

    answer = core.run_agent("infinite question", session=object())

    assert "tool-call limit" in answer


def test_run_agent_requires_api_key(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        core.run_agent("anything", session=object())


def test_system_prompt_is_cached():
    assert core.SYSTEM_BLOCKS == [
        {"type": "text", "text": core.SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
    ]


def test_first_request_marks_the_question_as_a_cache_breakpoint(monkeypatch):
    responses = [FakeResponse([FakeTextBlock("Keep Bijan.")], "end_turn")]
    client = _patch_client(monkeypatch, responses)

    core.run_agent("who should I keep?", session=object())

    sent_messages = client.messages.calls[0]["messages"]
    assert sent_messages[0]["content"] == [
        {"type": "text", "text": "who should I keep?", "cache_control": {"type": "ephemeral"}}
    ]
    assert client.messages.calls[0]["system"] == core.SYSTEM_BLOCKS


def test_cache_breakpoint_moves_forward_instead_of_accumulating(monkeypatch):
    monkeypatch.setitem(
        core.TOOL_HANDLERS, "get_league_info", lambda session, **kwargs: {"ok": True}
    )
    responses = [
        FakeResponse([FakeToolUseBlock("get_league_info", {})], "tool_use"),
        FakeResponse([FakeTextBlock("Done.")], "end_turn"),
    ]
    client = _patch_client(monkeypatch, responses)

    core.run_agent("what are the league rules?", session=object())

    # On the second request, only the newest (last) message's last block should
    # carry a breakpoint -- the first message's must have been cleared, not left
    # in place (that would eventually exceed the 4-breakpoints-per-request cap).
    second_call_messages = client.messages.calls[1]["messages"]
    first_msg_content = second_call_messages[0]["content"]
    assert "cache_control" not in first_msg_content[0]

    last_msg_content = second_call_messages[-1]["content"]
    assert last_msg_content[-1]["cache_control"] == {"type": "ephemeral"}
