"""
Dual-Pass LLM Engine
  Layer 1 — Dreamer (Consciousness): temp=0.7, streaming, free text
  Layer 2 — Executor (Translator): temp=0.1, JSON schema, deterministic
"""
import json
import re
import requests

from config import (
    OLLAMA_BASE_URL, SMART_MODEL, ASSISTANT_NAME,
    CONSCIOUSNESS_TEMP, EXECUTOR_TEMP, SUMMARY_TEMP,
    NUM_CTX, NUM_PREDICT, BASH_MAX_OUTPUT,
)
from prompts import (
    ACTION_INTENT_SYSTEM_PROMPT,
    EXECUTOR_SYSTEM_PROMPT,
    LANGUAGE_REMINDER
)

CHAT_URL = f"{OLLAMA_BASE_URL}/api/chat"

DEBUG_THINK = True



def consciousness_call(messages: list, system: str | None = None) -> str:
    """
    Dreamer: temp=0.7, streaming active, generates free text.
    NO JSON or format restrictions. Root'un ta kendisi.
    """
    full_messages = []

    if system:
        system_with_lang = system + LANGUAGE_REMINDER
        full_messages.append({"role": "system", "content": system_with_lang})

    full_messages.extend(messages)

    resp = requests.post(CHAT_URL, json={
        "model": SMART_MODEL,
        "messages": full_messages,
        "stream": True,
        "think": False,
        "options": {
            "temperature": CONSCIOUSNESS_TEMP,
            "top_p": 0.95,
            "top_k": 40,
            "min_p": 0.05,
            "repeat_penalty": 1.05,
            "num_ctx": NUM_CTX,
            "num_predict": NUM_PREDICT,
        },
    }, stream=True, timeout=120)
    resp.raise_for_status()

    visible_content = ""    
    in_think_block = False
    printed_root = False
    native_reasoning_active = False
    _repeat_buf = ""         
    _repeat_count = 0

    for line in resp.iter_lines():
        if not line:
            continue
        try:
            chunk = json.loads(line)
        except Exception:
            continue

        msg = chunk.get("message", {})

        reasoning = msg.get("reasoning", "") or chunk.get("reasoning", "") or msg.get("thinking", "")
        if reasoning:
            if not in_think_block:
                print("\n[THINK]\n", end="", flush=True)
                in_think_block = True
                native_reasoning_active = True

            _repeat_buf += reasoning
            if len(_repeat_buf) > 600:
                last_200 = _repeat_buf[-200:]
                prev_text = _repeat_buf[:-200]
                if last_200 in prev_text:
                    _repeat_count += 1
                else:
                    _repeat_count = 0
                if _repeat_count >= 2:
                    print("\n[Repetition loop detected, cutting thought...]\n", flush=True)
                    resp.close()
                    break
                _repeat_buf = _repeat_buf[-400:]

            if DEBUG_THINK:
                print(reasoning, end="", flush=True)

        content_token = msg.get("content", "")
        if content_token:
            if native_reasoning_active:
                print(f"\n[/THINK]\n\n{ASSISTANT_NAME}: ", end="", flush=True)
                in_think_block = False
                native_reasoning_active = False
                printed_root = True

            visible_content += content_token

            if len(visible_content) > 600:
                last_200 = visible_content[-200:]
                if last_200 in visible_content[:-200]:
                    _repeat_count += 1
                else:
                    _repeat_count = 0
                if _repeat_count >= 2:
                    print("\n[Repetition loop detected, cutting response...]\n", flush=True)
                    resp.close()
                    visible_content = visible_content[:-200]
                    break

            display_token = content_token

            if "<think>" in display_token:
                display_token = display_token.replace("<think>", "\n[THINK]\n")
                in_think_block = True
            if "</think>" in display_token:
                display_token = display_token.replace("</think>", "\n[/THINK]\n\n")
                in_think_block = False
                if not printed_root:
                    display_token += f"{ASSISTANT_NAME}: "
                    printed_root = True

            if not in_think_block and not printed_root and display_token.strip() and not display_token.startswith("\n[THINK"):
                print(f"{ASSISTANT_NAME}: ", end="", flush=True)
                printed_root = True

            print(display_token, end="", flush=True)

    if in_think_block:
        print("\n[/THINK]\n", flush=True)

    visible_content = re.sub(r'<think>.*?</think>', '', visible_content, flags=re.DOTALL)
    visible_content = re.sub(r'<think>.*$', '', visible_content, flags=re.DOTALL)
    visible_content = re.sub(r'</?think>', '', visible_content)
    visible_content = visible_content.strip()

    if not visible_content.strip():
        print("[Fallback: requesting short answer...]", flush=True)
        fallback_resp = requests.post(CHAT_URL, json={
            "model": SMART_MODEL,
            "messages": full_messages,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": NUM_PREDICT},
        }, timeout=60)
        fallback_resp.raise_for_status()
        visible_content = fallback_resp.json().get("message", {}).get("content", "")
        print(f"{ASSISTANT_NAME}: {visible_content}", flush=True)

    print()
    return visible_content.strip()



def consciousness_call_sync(messages: list, system: str | None = None) -> str:
    """
    Dreamer: temp=0.7, streaming OFF.
    Returns a single complete response (used in Telegram and similar environments).
    """
    full_messages = []

    if system:
        system_with_lang = system + LANGUAGE_REMINDER
        full_messages.append({"role": "system", "content": system_with_lang})

    full_messages.extend(messages)

    try:
        resp = requests.post(CHAT_URL, json={
            "model": SMART_MODEL,
            "messages": full_messages,
            "stream": False,
            "think": True,
            "options": {
                "temperature": CONSCIOUSNESS_TEMP,
                "top_p": 0.95,
                "top_k": 20,
                "min_p": 0.05,
                "repeat_penalty": 1.15,
                "num_ctx": NUM_CTX,
                "num_predict": NUM_PREDICT,
            },
        }, timeout=180)
        resp.raise_for_status()
        data = resp.json()
        content = data.get("message", {}).get("content", "")
        content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL)
        content = re.sub(r'<think>.*$', '', content, flags=re.DOTALL)
        content = re.sub(r'</?think>', '', content)
        return content.strip()
    except Exception as e:
        return f"[Error: Consciousness call failed: {e}]"



def executor_call(
    user_input: str,
    consciousness_text: str,
    entity_context: str = "",
    allow_regex_fallback: bool = True,
) -> list[dict]:
    """
    Executor: temp=0.1, JSON required, no streaming.
    Extracts physical action intents from Dreamer's free text.
    Single action -> [{...}], multiple actions -> [{...}, {...}, ...]
    Always returns list[dict].
    """
    user_content = f"User Prompt: {user_input}\n\nAssistant's Response: {consciousness_text}"
    if entity_context:
        user_content += f"\n\nRecently used items:\n{entity_context}"

    messages = [
        {"role": "system", "content": EXECUTOR_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    try:
        resp = requests.post(CHAT_URL, json={
            "model": SMART_MODEL,
            "messages": messages,
            "stream": False,
            "think": True,
            "format": "json",
            "options": {
                "temperature": EXECUTOR_TEMP,
                "num_ctx": NUM_CTX,
                "num_predict": 1024,
            },
        }, timeout=60)
        resp.raise_for_status()

        raw = resp.json().get("message", {}).get("content", "")
        content = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        parsed = json.loads(content)

        if isinstance(parsed, dict):
            return [parsed]
        if isinstance(parsed, list):
            return [a for a in parsed if isinstance(a, dict)]
        return [{"action": "none"}]

    except json.JSONDecodeError:
        if allow_regex_fallback:
            print("\n[WARNING] Executor produced broken JSON. Attempting regex rescue...")
            return [_parse_json_fallback(content)]
        print("\n[WARNING] Executor broken JSON. Fallback disabled; action: none")
        return [{"action": "none"}]
    except Exception as e:
        print(f"\n[WARNING] Executor error: {e}")
        return [{"action": "none"}]


def action_intent_call(user_input: str, consciousness_text: str) -> bool:
    """0.1 temp decision layer: does a tool call need to be made?"""
    messages = [
        {"role": "system", "content": ACTION_INTENT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"User Prompt: {user_input}\n\n"
                f"Assistant's Response: {consciousness_text}"
            ),
        },
    ]

    try:
        resp = requests.post(CHAT_URL, json={
            "model": SMART_MODEL,
            "messages": messages,
            "stream": False,
            "think": False,
            "format": "json",
            "options": {
                "temperature": EXECUTOR_TEMP,
                "num_ctx": NUM_CTX,
                "num_predict": 64,
            },
        }, timeout=30)
        resp.raise_for_status()

        raw = resp.json().get("message", {}).get("content", "")
        content = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        parsed = json.loads(content)
        return bool(parsed.get("has_action", False))
    except Exception as e:
        print(f"\n[WARNING] Action intent layer error: {e}")
        return False


def _parse_json_fallback(text: str) -> dict:
    """Tries to rescue action from broken JSON output (Resilience layer)."""
    match = re.search(r'\{.*"action"\s*:\s*"([^"]+)".*\}', text, re.DOTALL)
    if match:
        action = match.group(1)
        result = {"action": action}
        for key in ["command", "file", "content", "section", "new_content", "old", "new", "to_delete", "app", "window", "workspace_no", "search_query", "query", "depth", "url"]:
            key_match = re.search(rf'"{key}"\s*:\s*"([^"]*)"', text)
            if key_match:
                result[key] = key_match.group(1)
        print("[WARNING] Broken JSON rescued with regex!")
        return result

    print("[WARNING] JSON rescue failed. Action: none.")
    return {"action": "none"}



def summarize_output(output: str) -> str:
    """Summarizes very long tool outputs using LLM (temp=0.3, alt-ajan)."""
    summary_prompt = f"Summarize this command output in 3 sentences:\n{output[:5000]}"
    try:
        resp = requests.post(CHAT_URL, json={
            "model": SMART_MODEL,
            "messages": [{"role": "user", "content": summary_prompt}],
            "stream": False,
            "options": {
                "temperature": SUMMARY_TEMP,
                "num_predict": 200,
            },
        }, timeout=30)
        resp.raise_for_status()
        summary = resp.json().get("message", {}).get("content", "")
        return f"⚠️ Output too long, summarized:\n{summary}\n\n(First 500 chars: {output[:500]})"
    except Exception:
        return output[:BASH_MAX_OUTPUT] + "\n\n... (output truncated)"


def is_alive() -> bool:
    try:
        return requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5).status_code == 200
    except Exception:
        return False