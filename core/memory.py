import json
import uuid
import requests
import chromadb
from datetime import datetime

from config import (
    OLLAMA_BASE_URL, CHROMA_PERSIST_DIR, CHROMA_COLLECTION,
    MEMORY_TOP_K, SMART_MODEL, MAX_HISTORY_TOKENS, SLIDING_WINDOW_SIZE,
    ASSISTANT_NAME,
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

class Memory:
    def __init__(self):
        self.client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
        self.collection = self.client.get_or_create_collection(
            name=CHROMA_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )

    def save(self, user_input: str, assistant_response: str) -> bool:
        """Asks the LLM if the conversation is worth saving; saves if yes. Returns True/False."""
        if not _should_save(user_input, assistant_response):
            return False

        text = f"User: {user_input}\n{ASSISTANT_NAME}: {assistant_response}"
        try:
            embedding = _embed(text)
        except Exception as e:
            print(f"\n[WARNING] Embedding error (skipping record): {e}")
            return False
        self.collection.add(
            documents=[text],
            embeddings=[embedding],
            metadatas=[{"timestamp": datetime.now().isoformat()}],
            ids=[str(uuid.uuid4())],
        )
        return True

    def recall(self, query: str) -> str:
        count = self.collection.count()
        if count == 0:
            return ""

        try:
            embedding = _embed(query)
        except Exception as e:
            print(f"\n[WARNING] Embedding error (skipping recall): {e}")
            return ""
        results = self.collection.query(
            query_embeddings=[embedding],
            n_results=min(MEMORY_TOP_K, count),
            include=["documents", "distances"],
        )

        memories = []
        for doc, dist in zip(results["documents"][0], results["distances"][0]):
            if dist < 0.5:
                memories.append(doc)

        if not memories:
            return ""

        return "From past conversations:\n" + "\n---\n".join(memories)

    def count(self) -> int:
        return self.collection.count()



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