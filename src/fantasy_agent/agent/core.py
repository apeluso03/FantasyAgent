"""Agent core: a manual Claude tool-calling loop over the fantasy_agent tools.

Manual, not the SDK's beta tool_runner, so every tool call and its result is
visible and logged — per the spec's design notes, that trace is the point:
"here's how it thinks" is as much the deliverable as the final answer.
"""

from __future__ import annotations

import json
import logging

import anthropic
from sqlalchemy.orm import Session

from ..config import settings
from .tools import TOOL_HANDLERS, TOOL_SCHEMAS, ToolError

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a fantasy football assistant for a 12-team PPR superflex keeper \
league on Sleeper. You help with keeper decisions, trade evaluation, and general roster \
questions, grounded only in the data your tools return -- never invent player ranks, roster \
contents, or league rules.

Call whatever tools you need (you may call several, across multiple turns) before answering. \
When you give a recommendation, briefly explain the reasoning using the specific numbers the \
tools returned, not just a verdict."""

# system+tools are byte-identical on every call, so caching them turns that fixed
# overhead into a ~0.1x-cost cache read after the first request (same session, and
# even across separate `ask` calls within the ~5min TTL).
CACHE_CONTROL = {"type": "ephemeral"}
SYSTEM_BLOCKS = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": CACHE_CONTROL}]

MAX_TOOL_ITERATIONS = 8


def _apply_cache_breakpoint(messages: list[dict]) -> None:
    """Mark the last content block of the last message as a cache breakpoint,
    clearing any earlier one first (max 4 breakpoints/request, and we only ever
    want one here). Each round of the tool loop then only pays full price for
    what's new since the previous request -- everything before it reads from
    cache instead of being rebilled as the growing history gets resent.
    """
    for msg in messages[:-1]:
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    block.pop("cache_control", None)

    last_content = messages[-1].get("content")
    if isinstance(last_content, str):
        messages[-1]["content"] = [{"type": "text", "text": last_content, "cache_control": CACHE_CONTROL}]
    elif isinstance(last_content, list) and last_content:
        last_content[-1]["cache_control"] = CACHE_CONTROL


def run_agent(question: str, session: Session, *, model: str | None = None) -> str:
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set -- add it to .env to use `fantasy-agent ask`.")

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    model = model or settings.anthropic_model
    messages: list[dict] = [{"role": "user", "content": question}]

    for _ in range(MAX_TOOL_ITERATIONS):
        _apply_cache_breakpoint(messages)
        response = client.messages.create(
            model=model,
            max_tokens=settings.anthropic_max_tokens,
            system=SYSTEM_BLOCKS,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )
        usage = response.usage
        logger.info(
            "usage input=%d cache_read=%d cache_write=%d output=%d",
            usage.input_tokens,
            getattr(usage, "cache_read_input_tokens", 0) or 0,
            getattr(usage, "cache_creation_input_tokens", 0) or 0,
            usage.output_tokens,
        )

        if response.stop_reason != "tool_use":
            return "".join(block.text for block in response.content if block.type == "text")

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            logger.info("tool_call %s(%s)", block.name, json.dumps(block.input))
            handler = TOOL_HANDLERS.get(block.name)
            if handler is None:
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Unknown tool: {block.name}",
                        "is_error": True,
                    }
                )
                continue
            try:
                result = handler(session, **block.input)
                content = json.dumps(result)
                is_error = False
            except ToolError as exc:
                content = str(exc)
                is_error = True
            logger.info("tool_result %s -> %s", block.name, content[:500])
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": content, "is_error": is_error}
            )

        messages.append({"role": "user", "content": tool_results})

    return "Reached the tool-call limit without a final answer -- try a narrower question."
