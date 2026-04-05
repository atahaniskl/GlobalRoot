"""
Auto-Dream V2 — Autonomous Neural Maintenance Daemon
=====================================================
Designed to run headless (no UI, no terminal interaction).
Can be triggered from:
  1. main.py startup hook  (perform_startup_dreaming)
  2. systemd timer / cron  (python -m core.auto_dream)

Three maintenance passes:
  Pass 1 — Knowledge Consolidation (LLM reads yesterday's journal)
  Pass 2 — Neural Graph Extraction (regex [[links]], NetworkX export)
  Pass 3 — Memory Decay (archive notes untouched for MEMORY_DECAY_DAYS)
"""

import json
import re
import sys
import requests
from datetime import datetime, timedelta
from pathlib import Path

# ── Lazy imports for headless compatibility ──────────────────────────────────
try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False


# ── Constants ────────────────────────────────────────────────────────────────
DREAM_MAX_OUTPUT_TOKENS = 800
DREAM_REPEAT_WINDOW = 300


def _log(msg: str, color: str = "0"):
    """Print with optional ANSI color. Silent-safe for headless."""
    try:
        print(f"\033[{color}m{msg}\033[0m", flush=True)
    except Exception:
        pass


def _get_file_content(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _write_file_safely(path: Path, content: str):
    if not content.strip():
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except Exception:
        pass


def _load_config():
    """Load config values. Works both as module import and standalone script."""
    try:
        from config import (
            OLLAMA_BASE_URL, SMART_MODEL, OBSIDIAN_VAULT_DIR,
            VAULT_DIR_MEMORY, VAULT_DIR_JOURNALS, VAULT_DIR_NEURAL_GRAPH,
            MEMORY_DECAY_DAYS, MEMORY_DECAY_ARCHIVED_PRIORITY,
        )
        return {
            "OLLAMA_BASE_URL": OLLAMA_BASE_URL,
            "SMART_MODEL": SMART_MODEL,
            "VAULT_DIR": Path(OBSIDIAN_VAULT_DIR).expanduser().resolve(),
            "DIR_MEMORY": VAULT_DIR_MEMORY,
            "DIR_JOURNALS": VAULT_DIR_JOURNALS,
            "DIR_NEURAL_GRAPH": VAULT_DIR_NEURAL_GRAPH,
            "DECAY_DAYS": MEMORY_DECAY_DAYS,
            "DECAY_PRIORITY": MEMORY_DECAY_ARCHIVED_PRIORITY,
        }
    except ImportError:
        # Fallback for standalone execution
        return {
            "OLLAMA_BASE_URL": "http://localhost:11434",
            "SMART_MODEL": "qwen3.5:4b",
            "VAULT_DIR": Path.home() / "Obsidian" / "Kasa",
            "DIR_MEMORY": "_memory",
            "DIR_JOURNALS": "journals",
            "DIR_NEURAL_GRAPH": "neural_graph",
            "DECAY_DAYS": 60,
            "DECAY_PRIORITY": "archived",
        }


# ═════════════════════════════════════════════════════════════════════════════
# PASS 1 — Knowledge Consolidation (LLM reads yesterday's journal)
# ═════════════════════════════════════════════════════════════════════════════

def _pass1_consolidate(cfg: dict) -> bool:
    """Read yesterday's journal, extract knowledge into core memory files."""
    vault = cfg["VAULT_DIR"]

    # -- V2: Support both old (Journals/, _Memory/) and new (journals/, _memory/) paths --
    memory_dir = vault / cfg["DIR_MEMORY"]
    if not memory_dir.exists():
        memory_dir_legacy = vault / "_Memory"
        if memory_dir_legacy.exists():
            memory_dir = memory_dir_legacy
        else:
            memory_dir.mkdir(parents=True, exist_ok=True)

    # Time-based smart trigger: check last_run_timestamp
    ledger_path = memory_dir / "last_dream_timestamp.json"
    last_run = 0.0
    if ledger_path.exists():
        try:
            data = json.loads(ledger_path.read_text("utf-8"))
            last_run = float(data.get("timestamp", 0.0))
        except Exception:
            pass

    import time
    now_ts = time.time()
    
    # 1. Has enough time passed? (At least 8 hours to avoid spamming on every restart)
    hours_since = (now_ts - last_run) / 3600
    if now_ts - last_run < 8 * 3600:
        _log(f"[Subconscious] Pass 1: Cooldown active ({hours_since:.1f}h / 8h). Skipping consolidation.", "90")
        return False

    # 2. Are there new files in journals/ or conversations/?
    new_files = []
    
    def _scan_dir(d_path):
        if d_path.exists():
            for f in d_path.rglob("*.md"):
                if f.is_file() and f.stat().st_mtime > last_run:
                    new_files.append(f)
                    
    _scan_dir(vault / cfg["DIR_JOURNALS"])
    _scan_dir(vault / "Journals")
    _scan_dir(vault / "conversations")

    if not new_files:
        # No new conversations since last dream. Just update timestamp and sleep.
        _log("[Subconscious] Pass 1: No new interactions found. Skipping.", "90")
        _write_file_safely(ledger_path, json.dumps({"timestamp": now_ts}))
        return False

    _log(f"[Subconscious] Pass 1: Found {len(new_files)} new interaction files. Consolidating...", "96")
    
    # Combine content of new files
    recent_memories = ""
    for f in new_files:
        recent_memories += f"\n--- {f.name} ---\n"
        recent_memories += f.read_text(encoding="utf-8", errors="ignore")[:4000]

    diary_content = recent_memories

    soul_content = _get_file_content(memory_dir / "SOUL.md")
    user_content = _get_file_content(memory_dir / "USER.md")
    wisdom_content = _get_file_content(memory_dir / "WISDOM.md")

    prompt = f"""You are the Subconscious Dreamer of GlobalRoot.
Your job is to read the recent DIARY and extract NEW knowledge into the core files.

[CURRENT FILES]
=== SOUL.md ===
{soul_content}

=== USER.md ===
{user_content}

=== WISDOM.md ===
{wisdom_content}

[RECENT DIARY / MEMORIES]
{diary_content[-6000:]}

[INSTRUCTIONS]
1. Read the diary carefully. Extract ONLY genuinely new information.
2. If you learned a new user habit → add a short bullet for USER_APPEND.
3. If you learned a new AI rule/tactic → add a short bullet for SOUL_APPEND.
4. If you learned a raw technical fact/command → add a short bullet for WISDOM_APPEND.
5. If nothing new was learned for a category, set its value to empty string "".
6. Each bullet must be ONE short line starting with "- ".
7. Do NOT repeat information already in the current files above.

CRITICAL: Reply with ONLY a single JSON object. No markdown, no explanation, no extra text.

{{"SOUL_APPEND": "- new rule here", "USER_APPEND": "- new user habit here", "WISDOM_APPEND": "- new technical fact here"}}"""

    chat_url = f"{cfg['OLLAMA_BASE_URL']}/api/chat"
    try:
        resp = requests.post(chat_url, json={
            "model": cfg["SMART_MODEL"],
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0.3,
                "repeat_penalty": 1.2,
                "num_predict": DREAM_MAX_OUTPUT_TOKENS,
                "num_ctx": 8192,
            }
        }, timeout=180)
        resp.raise_for_status()
        raw = resp.json().get("message", {}).get("content", "")
    except Exception as e:
        _log(f"[Subconscious] Pass 1 failed: {e}", "91")
        return False

    # Clean think blocks
    clean = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
    start_idx = clean.find('{')
    end_idx = clean.rfind('}')
    if start_idx == -1 or end_idx == -1:
        _log("[Subconscious] Pass 1: No JSON found in response.", "93")
        _write_file_safely(ledger_path, json.dumps({"timestamp": now_ts}))
        return False

    try:
        data = json.loads(clean[start_idx:end_idx + 1])
    except json.JSONDecodeError:
        _log("[Subconscious] Pass 1: JSON parse error.", "93")
        _write_file_safely(ledger_path, json.dumps({"timestamp": now_ts}))
        return False

    from tools.memory_tools import append_to_memory
    count = 0

    def _safe(fname, section, text):
        nonlocal count
        if text and len(text.strip()) > 3:
            # Clean up potential multi-line response to single lines for logging
            clean_text = text.strip().replace("\n", " ")
            _log(f"  [+] {fname} -> {section}: {clean_text}", "32") # Green for added content
            res = append_to_memory(fname, section, text)
            if "✅" in res:
                count += 1

    _safe("SOUL.md", "RULES", data.get("SOUL_APPEND", ""))
    _safe("USER.md", "NOTES", data.get("USER_APPEND", ""))
    _safe("WISDOM.md", "TECHNICAL FACTS", data.get("WISDOM_APPEND", ""))

    _write_file_safely(ledger_path, json.dumps({"timestamp": now_ts}))
    _log(f"[Subconscious] Pass 1 complete: {count} item(s) consolidated.", "92")
    return True


# ═════════════════════════════════════════════════════════════════════════════
# PASS 2 — Neural Graph Extraction (regex [[links]], NetworkX export)
# ═════════════════════════════════════════════════════════════════════════════

def _pass2_build_graph(cfg: dict) -> bool:
    """Scan all .md files, extract [[links]], build NetworkX graph, export."""
    vault = cfg["VAULT_DIR"]
    graph_dir = vault / cfg["DIR_NEURAL_GRAPH"]
    graph_dir.mkdir(parents=True, exist_ok=True)

    if not HAS_NETWORKX:
        _log("[Subconscious] Pass 2 skipped: networkx not installed.", "93")
        return False

    G = nx.DiGraph()
    link_pattern = re.compile(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]')

    md_files = list(vault.rglob("*.md"))
    # Exclude hidden dirs and .root_index
    md_files = [f for f in md_files if not any(
        part.startswith('.') for part in f.relative_to(vault).parts
    )]

    for md_file in md_files:
        node_name = md_file.stem
        rel_path = str(md_file.relative_to(vault))

        # Read frontmatter for priority
        content = md_file.read_text(encoding="utf-8", errors="ignore")
        priority = "active"
        fm_match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
        if fm_match:
            pm = re.search(r'priority:\s*(\S+)', fm_match.group(1))
            if pm:
                priority = pm.group(1)

        G.add_node(node_name, path=rel_path, priority=priority)

        # Find all [[links]]
        links = link_pattern.findall(content)
        for link in links:
            target = link.strip()
            G.add_edge(node_name, target)

    # Export as JSON (LLM-readable)
    graph_data = {
        "generated": datetime.now().isoformat(),
        "total_nodes": G.number_of_nodes(),
        "total_edges": G.number_of_edges(),
        "nodes": [],
        "edges": [],
    }

    for node, attrs in G.nodes(data=True):
        in_deg = G.in_degree(node)
        out_deg = G.out_degree(node)
        graph_data["nodes"].append({
            "name": node,
            "path": attrs.get("path", ""),
            "priority": attrs.get("priority", "active"),
            "incoming_links": in_deg,
            "outgoing_links": out_deg,
            "importance": in_deg + out_deg,
        })

    for src, dst in G.edges():
        graph_data["edges"].append({"source": src, "target": dst})

    # Sort nodes by importance descending
    graph_data["nodes"].sort(key=lambda n: n["importance"], reverse=True)

    _write_file_safely(graph_dir / "graph.json", json.dumps(graph_data, indent=2, ensure_ascii=False))

    # Also write a human-readable summary
    top_nodes = graph_data["nodes"][:20]
    summary_lines = [
        f"# Neural Graph Summary",
        f"Generated: {graph_data['generated']}",
        f"Total nodes: {graph_data['total_nodes']}",
        f"Total synapses (edges): {graph_data['total_edges']}",
        "",
        "## Top 20 Most Connected Nodes",
    ]
    for n in top_nodes:
        summary_lines.append(
            f"- **{n['name']}** ({n['importance']} links) — {n['priority']} — `{n['path']}`"
        )

    _write_file_safely(graph_dir / "summary.md", "\n".join(summary_lines))

    _log(f"[Subconscious] Pass 2 complete: {G.number_of_nodes()} nodes, {G.number_of_edges()} synapses mapped.", "92")
    return True


# ═════════════════════════════════════════════════════════════════════════════
# PASS 3 — Memory Decay (archive stale notes)
# ═════════════════════════════════════════════════════════════════════════════

def _pass3_memory_decay(cfg: dict) -> bool:
    """Downgrade priority of notes not accessed/linked in MEMORY_DECAY_DAYS."""
    vault = cfg["VAULT_DIR"]
    decay_days = cfg["DECAY_DAYS"]
    archive_priority = cfg["DECAY_PRIORITY"]
    cutoff = datetime.now() - timedelta(days=decay_days)
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    # Read current graph for link counts
    graph_path = vault / cfg["DIR_NEURAL_GRAPH"] / "graph.json"
    linked_nodes = set()
    if graph_path.exists():
        try:
            gdata = json.loads(graph_path.read_text("utf-8"))
            for edge in gdata.get("edges", []):
                linked_nodes.add(edge["source"])
                linked_nodes.add(edge["target"])
        except Exception:
            pass

    archived_count = 0
    md_files = list(vault.rglob("*.md"))
    md_files = [f for f in md_files if not any(
        part.startswith('.') for part in f.relative_to(vault).parts
    )]

    for md_file in md_files:
        content = md_file.read_text(encoding="utf-8", errors="ignore")

        # Parse frontmatter
        fm_match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
        if not fm_match:
            continue  # No frontmatter — skip (core files like SOUL.md)

        fm_text = fm_match.group(1)

        # Check current priority
        pm = re.search(r'priority:\s*(\S+)', fm_text)
        current_priority = pm.group(1) if pm else "active"
        if current_priority == archive_priority:
            continue  # Already archived

        # Check last_accessed
        la_match = re.search(r'last_accessed:\s*(\S+)', fm_text)
        if not la_match:
            continue  # No last_accessed field — skip

        last_accessed = la_match.group(1)
        if last_accessed >= cutoff_str:
            continue  # Recently accessed

        # Check if node has recent links
        node_name = md_file.stem
        if node_name in linked_nodes:
            continue  # Still connected in the graph — keep active

        # Archive it: update priority in frontmatter
        if pm:
            new_fm = fm_text.replace(f"priority: {current_priority}", f"priority: {archive_priority}")
        else:
            new_fm = fm_text + f"\npriority: {archive_priority}"

        new_content = content[:fm_match.start(1)] + new_fm + content[fm_match.end(1):]
        _write_file_safely(md_file, new_content)
        _log(f"  [-] Archiving stale note: {md_file.name}", "90") # Gray for archival
        archived_count += 1

    if archived_count > 0:
        _log(f"[Subconscious] Pass 3 complete: {archived_count} note(s) archived (>{decay_days} days inactive).", "92")
    else:
        _log(f"[Subconscious] Pass 3 complete: All notes active.", "92")
    return True


# ═════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═════════════════════════════════════════════════════════════════════════════

def perform_startup_dreaming() -> bool:
    """Called from main.py on startup. Runs all 3 passes sequentially."""
    _log("")
    _log("╔══════════════════════════════════════════════════╗", "96")
    _log("║       [Auto-Dream] Startup Dreaming Active       ║", "96")
    _log("╚══════════════════════════════════════════════════╝", "96")

    cfg = _load_config()

    p1 = _pass1_consolidate(cfg)
    p2 = _pass2_build_graph(cfg)
    p3 = _pass3_memory_decay(cfg)

    if p1 or p2 or p3:
        _log("[Auto-Dream] ✅ Startup dreaming complete.\n", "92")
    else:
        _log("[Auto-Dream] Nothing new to process.\n", "90")

    return p1 or p2 or p3


# ═════════════════════════════════════════════════════════════════════════════
# STANDALONE CLI — for systemd timer / cron
# Usage:  python -m core.auto_dream
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Add project root to path for imports
    sys.path.insert(0, str(Path(__file__).parent.parent))

    _log("=" * 60, "96")
    _log("[Auto-Dream V2] Headless daemon starting...", "96")
    _log("=" * 60, "96")

    result = perform_startup_dreaming()

    if result:
        _log("[Auto-Dream V2] Maintenance complete.", "92")
    else:
        _log("[Auto-Dream V2] Nothing to process.", "90")
