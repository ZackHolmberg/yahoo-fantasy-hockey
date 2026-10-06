"""The one LLM layer every script uses. Switch drivers in data/llm.json; nothing else changes.

    {"driver": "local"}                          # Qwen on this Mac (~/dev/claude-local-llm, :8734), started on demand
    {"driver": "claude", "claude_model": "sonnet"}  # the `claude` CLI in print mode, no tools

    import llm
    llm.complete("prompt")                       # -> text
    llm.complete_json("prompt")                  # -> dict (asks for JSON, extracts the first object, retries once)

The local model always thinks (intelligence over speed). Each call gets "think_tokens" (data/llm.json) on top of
max_tokens for its reasoning; if that runs out mid-thought, the reasoning so far is handed back for the final answer.

The LLM only reads and writes text: it understands the owner's messages, explains numbers the scripts computed,
and phrases texts. Every action is decided and checked by the scripts, whatever the driver.
"""
import json
import re
import subprocess
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent
CONFIG = REPO / "data/llm.json"
LOCAL = "http://127.0.0.1:8734"
LOCAL_CLI = Path.home() / "dev/claude-local-llm/llm"
CLAUDE_CLI = Path.home() / ".local/bin/claude"


def config():
    try:
        return json.loads(CONFIG.read_text())
    except (OSError, json.JSONDecodeError):
        return {"driver": "local"}


def _local_model():
    def ask():
        return json.load(urllib.request.urlopen(f"{LOCAL}/v1/models", timeout=3))["data"][0]["id"]
    try:
        return ask()
    except Exception:
        subprocess.Popen([str(LOCAL_CLI), "start"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    for _ in range(24):  # up to ~2 min for the model to load
        time.sleep(5)
        try:
            return ask()
        except Exception:
            pass
    raise RuntimeError("local model server didn't start (see ~/dev/claude-local-llm, `llm logs`)")


def _chat(messages, max_tokens, think):
    # enable_thinking is the switch Qwen3.5 obeys (it ignores /no_think); its reasoning comes back in "reasoning".
    # Thinking uses Qwen's recommended sampling: at low temperature it loops ("Wait, check again...").
    sampling = {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "presence_penalty": 1.5} if think else {"temperature": 0.2}
    body = {"model": _local_model(), "messages": messages, "max_tokens": max_tokens, **sampling,
            "chat_template_kwargs": {"enable_thinking": think}}
    req = urllib.request.Request(f"{LOCAL}/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=1200))["choices"][0]


def _local(prompt, system, max_tokens, think_tokens):
    """Always thinks: answers are worth more than speed here (~22 tokens/s, so a full budget is ~6 min)."""
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    choice = _chat(messages, max_tokens + think_tokens, True)
    out = (choice["message"].get("content") or "").split("</think>")[-1].strip()
    reasoning = (choice["message"].get("reasoning") or "").strip()
    if not out and reasoning:
        # it ran out of budget mid-thought (usually re-checking a finished answer in a loop):
        # keep the reasoning and have it write the final answer from it, rather than start over without it
        messages[-1]["content"] += (f"\n\nYour analysis so far (it ran out of room before answering):\n"
                                    f"{reasoning[:16000]}\n\nWrite only the final answer now.")
        out = (_chat(messages, max_tokens, False)["message"].get("content") or "").strip()
    if not out:
        raise RuntimeError(f"local model returned no content (finish_reason={choice.get('finish_reason')})")
    return out


def _claude(prompt, system, max_tokens, model):
    full = (system + "\n\n" if system else "") + prompt
    r = subprocess.run([str(CLAUDE_CLI), "-p", "--tools", "", "--no-session-persistence", "--model", model],
                       input=full, capture_output=True, text=True, timeout=300, cwd=REPO)
    if r.returncode:
        raise RuntimeError(f"claude CLI failed: {r.stderr.strip()[-300:]}")
    return "\n".join(l for l in r.stdout.splitlines() if not l.startswith("Permission allow rule")).strip()


def complete(prompt, system=None, max_tokens=600):
    c = config()
    if c.get("driver") == "claude":
        return _claude(prompt, system, max_tokens, c.get("claude_model", "sonnet"))
    return _local(prompt, system, max_tokens, int(c.get("think_tokens", 8192)))


def complete_json(prompt, system=None, max_tokens=600):
    """Ask for one JSON object; extract it; retry once with the parse error if it doesn't parse."""
    ask = prompt + "\n\nAnswer with ONE JSON object only: no prose, no markdown fences."
    text = complete(ask, system, max_tokens)
    for attempt in range(2):
        m = re.search(r"\{.*\}", text, re.S)
        try:
            return json.loads(m.group(0) if m else text)
        except json.JSONDecodeError as e:
            if attempt:
                raise ValueError(f"LLM didn't return valid JSON: {text[:300]}") from e
            text = complete(ask + f"\n\nYour previous answer wasn't valid JSON ({e}). Return only the JSON object.",
                            system, max_tokens)
