import json
import requests
from datetime import datetime
from pathlib import Path
import re

from config import (
    OLLAMA_BASE_URL, CHROMA_PERSIST_DIR, CHROMA_COLLECTION,
    MEMORY_TOP_K, SMART_MODEL, MAX_HISTORY_TOKENS, SLIDING_WINDOW_SIZE,
    ASSISTANT_NAME, OBSIDIAN_VAULT_DIR,
)
from prompts import MEMORY_JUDGE_PROMPT, MEMORY_JUDGE_SYSTEM

EMBED_URL  = f"{OLLAMA_BASE_URL}/api/embeddings"
CHAT_URL   = f"{OLLAMA_BASE_URL}/api/chat"


def _embed(text: str) -> list[float]:
    resp = requests.post(EMBED_URL, json={
        "model": "nomic-embed-text",
        "prompt": text,
    }, timeout=30)
    resp.raise_for_status()
    return resp.json()["embedding"]

def _should_save(user_input: str, assistant_response: str) -> bool:
    prompt = MEMORY_JUDGE_PROMPT.format(user_input=user_input, assistant_response=assistant_response)
    system_msg = MEMORY_JUDGE_SYSTEM

    try:
        resp = requests.post(CHAT_URL, json={
            "model": SMART_MODEL,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ],
            "stream": True,
            "think": False,
            "options": {
                "temperature": 0.1,
                "repeat_penalty": 1.1,
                "num_predict": 128,
                "num_ctx": 4096
            },
        }, stream=True, timeout=120)
        resp.raise_for_status()
    except Exception as e:
        print(f"\n[WARNING] Memory block failed with error: {e}. Skipping save.")
        return False

    full_content = ""
    in_think_block = False
    printed_root = False
    native_reasoning_active = False

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
                print("\n[Memory THINK]\n", end="", flush=True)
                in_think_block = True
                native_reasoning_active = True
            
            full_content += reasoning
            print(reasoning, end="", flush=True)

        content_token = msg.get("content", "")
        if content_token:
            if native_reasoning_active:
                print("\n[/Memory THINK]\n\n[Memory Decision]: ", end="", flush=True)
                in_think_block = False
                native_reasoning_active = False
                printed_root = True

            full_content += content_token
            
            display_token = content_token
            
            if "<think>" in display_token:
                display_token = display_token.replace("<think>", "\n[Memory THINK]\n")
                in_think_block = True
                
            if "</think>" in display_token:
                display_token = display_token.replace("</think>", "\n[/Memory THINK]\n\n")
                in_think_block = False
                if not printed_root:
                    display_token += "[Memory Decision]: "
                    printed_root = True

            if not in_think_block and not printed_root and display_token.strip() and not display_token.startswith("\n[Memory THINK"):
                print("[Memory Decision]: ", end="", flush=True)
                printed_root = True

            print(display_token, end="", flush=True)

    if in_think_block:
        print("\n[/Memory THINK]\n", flush=True)

    print("\n[Memory Decision Finished]", flush=True)
    answer = full_content.strip().lower()
    
    final_decision = False
    if "decision: yes" in answer:
        final_decision = True
    elif answer.endswith("yes"):
        final_decision = True
        
    print(f"[Model Decision Extraction]: {'YES (Saved)' if final_decision else 'NO (Discarded)'}", flush=True)
    return final_decision


def _classify_and_store(user_input: str, assistant_response: str):
    """Neural classifier: asks LLM which memory section the info belongs to,
    then auto-appends it using the structured memory_tools."""
    classify_prompt = f"""You are a memory classifier. Given the conversation below, extract ONLY the key personal facts or preferences.
Then decide which file and section each fact belongs to.

Conversation:
User: {user_input}
Assistant: {assistant_response}

Available targets:
- USER.md / WHO AM I — for identity info (name, age, job, education)
- USER.md / PREFERENCES — for likes and preferred workflows
- USER.md / DISLIKES — for things user hates
- USER.md / SYSTEM SETUP — for OS, hardware, dev environment info
- USER.md / NOTES — for misc observations
- SOUL.md / 5 RULES — for new behavioral rules the agent should follow

Reply with ONLY a JSON array of objects. Each object has "file", "section", "content" (a short bullet starting with "- ").
If nothing worth saving, reply with an empty array [].
Example: [{{"file": "USER.md", "section": "WHO AM I", "content": "- Name: Atahan, 21 years old, CS 3rd year student"}}]"""

    try:
        resp = requests.post(CHAT_URL, json={
            "model": SMART_MODEL,
            "messages": [{"role": "user", "content": classify_prompt}],
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 256,
                "num_ctx": 4096,
            },
        }, timeout=60)
        resp.raise_for_status()
        raw = resp.json().get("message", {}).get("content", "").strip()
        
        # Extract JSON array
        start = raw.find('[')
        end = raw.rfind(']')
        if start == -1 or end == -1:
            return
        
        items = json.loads(raw[start:end+1])
        if not items:
            return
            
        from tools.memory_tools import append_to_memory
        
        for item in items:
            file_name = item.get("file", "")
            section = item.get("section", "")
            content = item.get("content", "")
            if file_name and section and content:
                result = append_to_memory(file_name, section, content)
                if "\u2705" in result:
                    print(f"[Neural Memory] {file_name}/{section} ← {content.strip()[:60]}", flush=True)
                elif "DUPLICATE" in result:
                    print(f"[Neural Memory] Skip (already exists): {content.strip()[:60]}", flush=True)
                else:
                    print(f"[Neural Memory] Warning: {result[:80]}", flush=True)
    except Exception as e:
        print(f"[Neural Memory Error] {type(e).__name__}: {e}", flush=True)

def _generate_topic_title(user_input: str) -> str:
    """Generates a very short topic title for the diary header."""
    prompt = f"Summarize the following topic in 2 to 4 words. Be highly descriptive but very short. Output ONLY the words, nothing else.\nUser: {user_input}"
    try:
        resp = requests.post(CHAT_URL, json={
            "model": SMART_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0.3,
                "num_predict": 10,
                "num_ctx": 1024,
            },
        }, timeout=10)
        resp.raise_for_status()
        raw = resp.json().get("message", {}).get("content", "").strip()
        # Clean quotes and think blocks just in case
        clean = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
        clean = clean.replace('"', '').replace("'", "")
        if clean and len(clean) < 40:
            return clean
    except:
        pass
    return "Conversation"

class Memory:
    def __init__(self):
        pass

    def save(self, user_input: str, assistant_response: str) -> bool:
        """Saves conversation to Daily Notes and runs neural classifier."""
        if not _should_save(user_input, assistant_response):
            return False

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        topic = _generate_topic_title(user_input)
        text = f"User: {user_input}\n{ASSISTANT_NAME}: {assistant_response}"
        diary_entry = f"## [{timestamp}] {topic}\n{text}\n\n"

        # 1. Save to Daily Notes (Source of Truth in Obsidian Vault)
        try:
            from config import VAULT_DIR_JOURNALS
            vault_path = Path(OBSIDIAN_VAULT_DIR).expanduser().resolve()
            now = datetime.now()
            year = now.strftime("%Y")
            month = now.strftime("%m-%B")
            day = now.strftime("%Y-%m-%d")
            
            # V2 path (snake_case), fallback to legacy
            journals_dir = vault_path / VAULT_DIR_JOURNALS
            if not journals_dir.exists():
                legacy = vault_path / "Journals"
                if legacy.exists():
                    journals_dir = legacy
                else:
                    journals_dir.mkdir(parents=True, exist_ok=True)
            
            diary_path = journals_dir / year / month / f"{day}.md"
            diary_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(diary_path, "a", encoding="utf-8") as f:
                f.write(diary_entry)
        except Exception as e:
            print(f"\n[WARNING] Could not write to Obsidian DIARY: {e}")

        # 2. Neural Classifier: file facts into correct memory sections
        try:
            _classify_and_store(user_input, assistant_response)
        except Exception as e:
            print(f"[WARNING] Neural classifier failed: {e}")

        # 3. Atomic Conversation Log (conversations/ directory)
        try:
            conv_dir = vault_path / "conversations"
            conv_dir.mkdir(parents=True, exist_ok=True)
            
            conv_ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            safe_topic = re.sub(r'[^\w\s-]', '', topic)[:40].strip().replace(' ', '_').lower()
            conv_filename = f"{conv_ts}_{safe_topic}.md"
            conv_path = conv_dir / conv_filename
            
            today = datetime.now().strftime("%Y-%m-%d")
            conv_content = f"""---
priority: high
last_accessed: {today}
topic: {topic}
---
# {topic}

**User:** {user_input}

**{ASSISTANT_NAME}:** {assistant_response}
"""
            conv_path.write_text(conv_content, encoding="utf-8")
        except Exception as e:
            print(f"[WARNING] Could not write conversation log: {e}")

        return True

    def recall(self, query: str) -> str:
        return ""



def trim_history(history: list, max_tokens: int = MAX_HISTORY_TOKENS) -> list:
    """
    Discards oldest messages with FIFO logic, preserves system messages.
    Token estimate: 1 token ≈ 4 characters.
    """
    system_msgs = [m for m in history if m["role"] == "system"]
    other_msgs = [m for m in history if m["role"] != "system"]

    if len(other_msgs) > SLIDING_WINDOW_SIZE:
        other_msgs = other_msgs[-SLIDING_WINDOW_SIZE:]

    total_chars = sum(len(str(m.get("content", ""))) for m in other_msgs)
    max_chars = max_tokens * 4

    while total_chars > max_chars and len(other_msgs) > 2:
        removed = other_msgs.pop(0)
        total_chars -= len(str(removed.get("content", "")))

    return system_msgs + other_msgs



class EntityTracker:
    """
    Tracks recently used files, commands, and other entities to resolve
    pronoun references like "delete it" or "look at that".
    Provided to the Executor as additional context.
    """
    def __init__(self):
        self.last_mentioned: dict[str, str] = {}

    def update(self, action: dict):
        """Update tracked entities from the Executor's parsed JSON object."""
        action_name = action.get("action", "")

        if action_name in ("read_file", "write_file"):
            file_path = action.get("file")
            if file_path:
                self.last_mentioned["file"] = file_path
        elif action_name == "bash":
            command = action.get("command", "")
            if command:
                self.last_mentioned["command"] = command
        elif action_name in ("memory_append", "memory_update", "memory_read"):
            section = action.get("section")
            if section:
                self.last_mentioned["memory_heading"] = section

    def get_context(self) -> str:
        """Returns entity context to be passed to the Executor."""
        if not self.last_mentioned:
            return ""
        lines = [f"- Last {k}: {v}" for k, v in self.last_mentioned.items()]
        return "\n".join(lines)