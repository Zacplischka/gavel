"""Shared plumbing for the optional live-LLM paths.

Everything here is OFF by default. Nothing in the offline test suite or the
default CLI flow calls a model; see ``docs/adr/0004-optional-llm-judge.md``.

Two transports are provided:

* ``call_claude_cli`` — shells out to the local ``claude`` CLI (``claude -p``).
* ``call_anthropic_api`` — raw HTTPS to the Anthropic Messages API using only
  stdlib ``urllib`` (no SDK dependency). Requires ``ANTHROPIC_API_KEY``.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_API_MODEL = "claude-opus-4-8"


class LLMUnavailableError(Exception):
    """Raised when a live-LLM transport cannot run (missing CLI, key, etc.)."""


def iter_json_objects(text: str) -> Iterator[dict[str, Any]]:
    """Yield every parseable top-level JSON object embedded in messy text.

    LLM output frequently wraps JSON in prose or code fences. This scans for
    balanced ``{...}`` spans (string-aware) and yields each one that parses.
    """
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"' and depth > 0:
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                candidate = text[start : i + 1]
                start = -1
                try:
                    parsed = json.loads(candidate)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    yield parsed


def call_claude_cli(
    prompt: str,
    *,
    model: str | None = None,
    command: str = "claude",
    timeout: float = 180.0,
) -> str:
    """Run ``claude -p <prompt>`` and return its stdout."""
    argv = [command, "-p", prompt, "--output-format", "text"]
    if model is not None:
        argv += ["--model", model]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise LLMUnavailableError(
            f"claude CLI not found ({command!r}); install it or use --judge deterministic"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise LLMUnavailableError(f"claude CLI timed out after {timeout}s") from exc
    if proc.returncode != 0:
        raise LLMUnavailableError(
            f"claude CLI exited with status {proc.returncode}: {proc.stderr.strip()[:500]}"
        )
    return proc.stdout


def call_anthropic_api(
    prompt: str,
    *,
    model: str | None = None,
    timeout: float = 180.0,
    max_tokens: int = 1024,
) -> str:
    """POST to the Anthropic Messages API via stdlib urllib and return the text.

    Deliberately SDK-free so the package keeps zero runtime dependencies.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise LLMUnavailableError(
            "ANTHROPIC_API_KEY is not set; the anthropic-api backend needs it "
            "(or use --judge deterministic, which is the offline default)"
        )
    body = json.dumps(
        {
            "model": model or DEFAULT_API_MODEL,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=body,
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise LLMUnavailableError(f"Anthropic API error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise LLMUnavailableError(f"Anthropic API unreachable: {exc.reason}") from exc
    if not isinstance(payload, dict):
        raise LLMUnavailableError("Anthropic API returned a non-object response")
    content = payload.get("content")
    if not isinstance(content, list):
        raise LLMUnavailableError("Anthropic API response missing content blocks")
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "".join(parts)
