"""Thin HTTP wrappers around the OpenAI and Anthropic REST APIs.
No heavy SDKs needed — just `requests` which is already installed.
Supports tool-calling / function-calling for the agent loop.
"""

import json
import os
import requests

from . import tools as T


def _headers_openai(key: str) -> dict:
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _headers_anthropic(key: str) -> dict:
    return {"x-api-key": key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}


# ── model listing ─────────────────────────────────────────────────────────────

def list_openai_models(api_key: str) -> list[str]:
    try:
        r = requests.get("https://api.openai.com/v1/models",
                         headers=_headers_openai(api_key), timeout=10)
        r.raise_for_status()
        ids = [m["id"] for m in r.json()["data"]]
        # keep only GPT chat models, sorted newest first
        gpt = sorted([x for x in ids if "gpt" in x and "instruct" not in x], reverse=True)
        return gpt or ids[:10]
    except Exception as e:
        return [f"error: {e}"]


def list_anthropic_models(api_key: str) -> list[str]:
    try:
        r = requests.get("https://api.anthropic.com/v1/models",
                         headers=_headers_anthropic(api_key), timeout=10)
        r.raise_for_status()
        ids = [m["id"] for m in r.json().get("data", [])]
        return ids if ids else ["claude-3-5-sonnet-20241022", "claude-3-haiku-20240307"]
    except Exception:
        return ["claude-3-5-sonnet-20241022", "claude-3-haiku-20240307",
                "claude-sonnet-4-5", "claude-opus-4-5"]


# ── single turn (no tools, for workflows) ─────────────────────────────────────

def complete(prompt: str, system: str, provider: str, api_key: str, model: str) -> str:
    if provider == "openai":
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=_headers_openai(api_key),
            json={"model": model, "max_tokens": 1024,
                  "messages": [{"role": "system", "content": system},
                                {"role": "user",   "content": prompt}]},
            timeout=60)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    else:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=_headers_anthropic(api_key),
            json={"model": model, "max_tokens": 1024, "system": system,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=60)
        r.raise_for_status()
        return r.json()["content"][0]["text"]


# ── agent loop (tool calling) ─────────────────────────────────────────────────

SYSTEM_PROMPT = """You are Priya, a friendly and organised AI Personal Assistant for Bhavana.

Your job areas:
• Career — job applications, follow-ups, study plans
• Baby — daily meal plans and feeding notes
• Business — notes and decisions from sister calls
• Study — learning tasks, reminders
• General — daily scheduling, preferences, reminders

Always call get_current_time before interpreting "today", "tomorrow" or day references.
When the user asks for a plan, break it into concrete tasks and events.
Save every preference or personal fact the user mentions using remember_preference.
Before creating a schedule, call list_preferences to recall the user's known habits.
Speak in a warm, concise tone. Use bullet points for lists.
"""


def _run_openai(messages: list, api_key: str, model: str) -> tuple[str, list]:
    """Returns (final_text, updated_messages). Runs the full tool-calling loop."""
    tool_specs = [{"type": "function", "function": s} for s in T.specs()]
    msgs = list(messages)
    for _ in range(10):          # max 10 tool hops
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=_headers_openai(api_key),
            json={"model": model, "messages": msgs, "tools": tool_specs,
                  "tool_choice": "auto", "max_tokens": 2048},
            timeout=90)
        r.raise_for_status()
        choice = r.json()["choices"][0]
        msg    = choice["message"]
        msgs.append(msg)

        if choice["finish_reason"] == "tool_calls":
            for tc in msg.get("tool_calls", []):
                result = T.call(tc["function"]["name"],
                                json.loads(tc["function"]["arguments"] or "{}"))
                msgs.append({"role": "tool", "tool_call_id": tc["id"],
                              "name": tc["function"]["name"], "content": result})
        else:
            return msg.get("content", ""), msgs

    return "I reached the step limit — please try again.", msgs


def _run_anthropic(messages: list, api_key: str, model: str) -> tuple[str, list]:
    """Returns (final_text, updated_messages). Anthropic tool-calling loop."""
    tool_specs = [{"name": s["name"], "description": s["description"],
                   "input_schema": s["parameters"]} for s in T.specs()]

    # Convert OpenAI-style history to Anthropic format (merge system out)
    def to_ant(m):
        if m["role"] in ("user", "assistant"):
            c = m.get("content", "")
            if isinstance(c, list):   # already Anthropic format
                return m
            return {"role": m["role"], "content": str(c)}
        return None

    msgs = [x for x in [to_ant(m) for m in messages] if x]

    for _ in range(10):
        body = {"model": model, "max_tokens": 2048, "system": SYSTEM_PROMPT,
                "tools": tool_specs, "messages": msgs}
        r = requests.post("https://api.anthropic.com/v1/messages",
                          headers=_headers_anthropic(api_key), json=body, timeout=90)
        r.raise_for_status()
        resp = r.json()

        # Build assistant message from response content blocks
        assistant_blocks = resp["content"]
        msgs.append({"role": "assistant", "content": assistant_blocks})

        if resp["stop_reason"] == "tool_use":
            tool_results = []
            for blk in assistant_blocks:
                if blk["type"] == "tool_use":
                    result = T.call(blk["name"], blk.get("input", {}))
                    tool_results.append({"type": "tool_result", "tool_use_id": blk["id"],
                                         "content": result})
            msgs.append({"role": "user", "content": tool_results})
        else:
            text = " ".join(b["text"] for b in assistant_blocks if b.get("type") == "text")
            return text.strip(), msgs

    return "I reached the step limit — please try again.", msgs


def run_agent(user_message: str, history: list, provider: str,
              api_key: str, model: str) -> tuple[str, list]:
    """Entry point. history is list of {role, content} dicts. Returns (reply, new_history)."""
    if provider == "openai":
        full = [{"role": "system", "content": SYSTEM_PROMPT}] + history + \
               [{"role": "user", "content": user_message}]
        reply, full = _run_openai(full, api_key, model)
        new_history = full[1:]           # strip system
        return reply, new_history
    else:
        msgs = history + [{"role": "user", "content": user_message}]
        reply, msgs = _run_anthropic(msgs, api_key, model)
        return reply, msgs
