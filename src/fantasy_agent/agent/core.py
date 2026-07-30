"""Agent core: a manual tool-calling loop over the fantasy_agent tools, using
OpenAI's Responses API (gpt-5.6-luna).

Manual, not a higher-level SDK helper, so every tool call and its result is
visible and logged -- per the spec's design notes, that trace is the point:
"here's how it thinks" is as much the deliverable as the final answer.

Unlike Claude's Messages API (this app's original provider), the Responses
API prices and applies prompt caching automatically server-side -- there's no
client-side cache_control bookkeeping to do here; the discounted "cached
input" pricing tier just applies on its own to repeated prefixes.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI
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

MAX_TOOL_ITERATIONS = 8


def run_agent(question: str, session: Session, *, model: str | None = None) -> str:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set -- add it to .env to use `fantasy-agent ask`.")

    client = OpenAI(api_key=settings.openai_api_key)
    model = model or settings.openai_model
    input_list: list[Any] = [{"role": "user", "content": question}]

    for _ in range(MAX_TOOL_ITERATIONS):
        response = client.responses.create(
            model=model,
            instructions=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            input=input_list,
        )

        usage = response.usage
        details = getattr(usage, "input_tokens_details", None)
        cached = (getattr(details, "cached_tokens", 0) or 0) if details is not None else 0
        logger.info(
            "usage input=%d cached=%d output=%d",
            getattr(usage, "input_tokens", 0) or 0,
            cached,
            getattr(usage, "output_tokens", 0) or 0,
        )

        # The model's own turn (text and/or function calls) becomes input context
        # for the next round -- the Responses API is a flat event list, not the
        # role-based message history Claude's Messages API uses.
        input_list += response.output

        function_calls = [item for item in response.output if item.type == "function_call"]
        if not function_calls:
            return response.output_text

        for call in function_calls:
            args = json.loads(call.arguments) if call.arguments else {}
            logger.info("tool_call %s(%s)", call.name, json.dumps(args))
            handler = TOOL_HANDLERS.get(call.name)
            if handler is None:
                output = f"Error: unknown tool {call.name}"
            else:
                try:
                    result = handler(session, **args)
                    output = json.dumps(result)
                except ToolError as exc:
                    output = f"Error: {exc}"
            logger.info("tool_result %s -> %s", call.name, output[:500])
            input_list.append({"type": "function_call_output", "call_id": call.call_id, "output": output})

    return "Reached the tool-call limit without a final answer -- try a narrower question."
