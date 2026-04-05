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
    SINGLE_PASS_SYSTEM_PROMPT,
    LANGUAGE_REMINDER
)

CHAT_URL = f"{OLLAMA_BASE_URL}/api/chat"

DEBUG_THINK = True



def consciousness_call(messages: list, system: str | None = None) -> tuple[str, list[dict]]:
    """
    Single-Pass Agent: temp=0.7, streaming active.
    Returns (visible_content, list_of_tool_action_dicts).
    """
    full_messages = []

    # Build system prompt: Tool instructions FIRST, then identity/memory files
    system_parts = [SINGLE_PASS_SYSTEM_PROMPT]
    if system:
        system_parts.append(system)
    system_parts.append(LANGUAGE_REMINDER)
    combined_system = "\n\n---\n\n".join(system_parts)
    full_messages.append({"role": "system", "content": combined_system})

    full_messages.extend(messages)

    resp = requests.post(CHAT_URL, json={
        "model": SMART_MODEL,
        "messages": full_messages,
        "stream": True,
        "think": True,
        "options": {
            "temperature": CONSCIOUSNESS_TEMP,
            "top_p": 0.95,
            "top_k": 40,
            "min_p": 0.05,
            "repeat_penalty": 1.15,
            "num_ctx": NUM_CTX,
            "num_predict": NUM_PREDICT,
        },
    }, stream=True, timeout=120)
    resp.raise_for_status()

    visible_content = ""
    raw_content = ""
    in_think_block = False
    think_closed = False
    in_tool_block = False
    printed_root = False
    
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

            print(reasoning, end="", flush=True)
            continue  # Don't add reasoning to raw_content

        content_token = msg.get("content", "")
        if content_token:
            # Close think block display when content starts
            if in_think_block and not think_closed:
                print("\n\n[/THINK]\n", flush=True)
                in_think_block = False
                think_closed = True
                
            raw_content += content_token
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
                    raw_content = raw_content[:-200] # Also trim raw
                    break

            display_token = content_token

            # Think tag parsing
            if "<think>" in display_token:
                display_token = display_token.replace("<think>", "\n[THINK]\n")
                in_think_block = True
            if "</think>" in display_token:
                display_token = display_token.replace("</think>", "\n[/THINK]\n\n")
                in_think_block = False
                if not printed_root:
                    display_token += f"{ASSISTANT_NAME}: "
                    printed_root = True

            # Tool tag parsing (hide from console)
            if "<tool_call>" in display_token:
                in_tool_block = True
                display_token = display_token.split("<tool_call>")[0]
            if "</tool_call>" in display_token:
                in_tool_block = False
                display_token = display_token.split("</tool_call>")[-1]

            if not in_think_block and not in_tool_block and not printed_root and display_token.strip() and not display_token.startswith("\n[THINK"):
                print(f"{ASSISTANT_NAME}: ", end="", flush=True)
                printed_root = True

            if not in_tool_block:
                print(display_token, end="", flush=True)

    if in_think_block and not think_closed:
        print("\n[/THINK]\n", flush=True)

    print()

    # Extract tool calls safely
    tool_calls = []
    tool_blocks = re.findall(r'<tool_call>\s*(.*?)\s*</tool_call>', raw_content, re.DOTALL)
    
    if not tool_blocks:
        # Fallback for "lazy" models that output raw JSON without XML tags
        match = re.search(r'(\{.*"action"\s*:\s*"[^"]+".*\})', raw_content, re.DOTALL)
        if match:
            tool_blocks = [match.group(1)]

    for block in tool_blocks:
        try:
            parsed = json.loads(block.strip())
            tool_calls.append(parsed)
        except json.JSONDecodeError:
            tool_calls.append(_parse_json_fallback(block))

    # Clean visible content
    clean_visible = re.sub(r'<think>.*?</think>', '', raw_content, flags=re.DOTALL)
    clean_visible = re.sub(r'<tool_call>.*?</tool_call>', '', clean_visible, flags=re.DOTALL)
    clean_visible = re.sub(r'<think>.*$', '', clean_visible, flags=re.DOTALL)
    clean_visible = re.sub(r'</?think>', '', clean_visible)
    clean_visible = clean_visible.strip()

    if not clean_visible and not tool_calls:
        print("\n\033[93m[Fallback: requesting short answer...]\033[0m", flush=True)
        try:
            fallback_resp = requests.post(CHAT_URL, json={
                "model": SMART_MODEL,
                "messages": full_messages,
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": NUM_PREDICT},
            }, timeout=120)
            fallback_resp.raise_for_status()
            clean_visible = fallback_resp.json().get("message", {}).get("content", "")
            print(f"{clean_visible}", flush=True)
        except Exception as e:
            print(f"\n\033[91m[Fallback Error] Could not retrieve answer from model: {e}\033[0m", flush=True)
            clean_visible = "Model processing failed. Please try again."
        return clean_visible, []

    # ── Forced Tool Extraction ────────────────────────────────────────────
    # If model produced text indicating action intent but forgot the <tool_call>,
    # fire a micro-query to extract the JSON action from its own response.
    # ONLY trigger when the model uses first-person action verbs, NOT when asking questions.
    if clean_visible and not tool_calls:
        # Negative signals: model is asking questions or presenting a menu
        lower_vis = clean_visible.lower()
        is_question = any(q in lower_vis for q in [
            "istersiniz", "ister misin", "hangisi", "ne yapalım",
            "would you like", "which one", "what do you want",
            "?",
        ])

        # Positive signals: model clearly states it WILL do something (first-person future)
        action_verbs = [
            "oluşturuyorum", "oluşturacağım", "yazıyorum", "yazacağım",
            "kaydediyorum", "ekliyorum", "başlıyorum", "yapıyorum",
            "kontrol ediyorum", "kontrol edeceğim", "bakıyorum", "okuyorum",
            "creating", "writing", "saving", "appending",
            "checking", "reading", "scanning", "looking up",
            "i will create", "i will write", "let me create",
        ]
        has_intent = any(v in lower_vis for v in action_verbs)

        if has_intent and not is_question:
            print("\033[93m[Tool Extractor] Model forgot tool_call, forcing extraction...\033[0m", flush=True)
            extract_prompt = f"""The AI assistant said the following but forgot to output the tool_call JSON.
Extract EXACTLY ONE JSON tool action from what it said. Pick the FIRST concrete action it said it is doing.
If the assistant is just talking, explaining, or asking a question, reply with: {{"action": "none"}}

Assistant's response: "{clean_visible}"

Available actions: bash, write_file, read_file, edit_file, write_to_obsidian, append_to_note, read_note, search_vault, memory_append, memory_read, open_app, none

Reply with ONLY the raw JSON object, nothing else.
Example: {{"action": "write_to_obsidian", "title": "MyProject", "content": "# Project notes", "folder": "Projects/MyProject"}}"""

            try:
                extract_resp = requests.post(CHAT_URL, json={
                    "model": SMART_MODEL,
                    "messages": [{"role": "user", "content": extract_prompt}],
                    "stream": False,
                    "think": False,
                    "options": {
                        "temperature": 0.1,
                        "num_predict": 300,
                        "num_ctx": 4096,
                    },
                }, timeout=60)
                extract_resp.raise_for_status()
                extract_raw = extract_resp.json().get("message", {}).get("content", "").strip()

                # Find JSON in response
                j_start = extract_raw.find('{')
                j_end = extract_raw.rfind('}')
                if j_start != -1 and j_end != -1:
                    extracted = json.loads(extract_raw[j_start:j_end+1])
                    if extracted.get("action", "none") != "none":
                        tool_calls.append(extracted)
                        print(f"\033[92m[Tool Extractor] Extracted: {extracted.get('action')}\033[0m", flush=True)
            except Exception as e:
                print(f"\033[91m[Tool Extractor Error] {e}\033[0m", flush=True)

    return clean_visible, tool_calls


def _parse_json_fallback(text: str) -> dict:
    """Tries to rescue action from broken JSON output (Resilience layer)."""
    match = re.search(r'\{.*"action"\s*:\s*"([^"]+)".*\}', text, re.DOTALL)
    if match:
        action = match.group(1)
        result = {"action": action}
        for key in [
            "command", "file", "content", "section", "new_content", "old", "new", "to_delete",
            "app", "window", "workspace_no", "search_query", "query", "depth", "url",
            "filename", "title", "folder", "key", "value", "tag", "new_folder"
        ]:
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