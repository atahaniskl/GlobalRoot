"""
Obsidian integration tools:
- Local semantic indexing (RAG) for Markdown notes
- Tool actions for searching, reading, and writing notes
- Reflection logging helpers for failed/corrected operations
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import chromadb
import requests

from config import (
    OLLAMA_BASE_URL,
    OBSIDIAN_VAULT_DIR,
    OBSIDIAN_EMBED_MODEL,
    OBSIDIAN_RAG_COLLECTION,
    OBSIDIAN_RAG_TOP_K,
    OBSIDIAN_RAG_MAX_CONTEXT_CHARS,
    OBSIDIAN_CHUNK_SIZE,
    OBSIDIAN_CHUNK_OVERLAP,
    OBSIDIAN_CORRECTIONS_DIR,
    CHROMA_PERSIST_DIR,
)

EMBED_URL = f"{OLLAMA_BASE_URL}/api/embeddings"
STATE_FILE = Path(CHROMA_PERSIST_DIR) / "obsidian_index_state.json"


@dataclass
class ReflectionFailure:
    timestamp: str
    action: dict
    error_result: str
    user_request: str


def _vault_path() -> Path:
    return Path(OBSIDIAN_VAULT_DIR).expanduser().resolve()


def _is_within(base: Path, target: Path) -> bool:
    try:
        target.relative_to(base)
        return True
    except ValueError:
        return False


def _iter_md_files(vault: Path) -> list[Path]:
    return sorted(vault.rglob("*.md"))


def _candidate_note_paths(vault: Path, filename: str) -> list[Path]:
    requested = _safe_note_name(filename)
    if not requested:
        return []

    candidates: list[Path] = []
    direct = (vault / requested).resolve()
    if direct.exists() and direct.is_file() and direct.suffix.lower() == ".md" and _is_within(vault, direct):
        candidates.append(direct)

    base_name = Path(requested).name.lower()
    for p in _iter_md_files(vault):
        if p.name.lower() == base_name and _is_within(vault, p.resolve()):
            if p not in candidates:
                candidates.append(p)

    return candidates


def _split_frontmatter(text: str) -> tuple[str, str, bool]:
    if not text.startswith("---\n"):
        return "", text, False

    m = re.match(r"^---\n(.*?)\n---\n?", text, flags=re.DOTALL)
    if not m:
        return "", text, False

    fm = m.group(1)
    body = text[m.end():]
    return fm, body, True


def _parse_frontmatter_map(frontmatter: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw in frontmatter.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def _render_frontmatter_map(mapping: dict[str, str]) -> str:
    lines = [f"{k}: {v}" for k, v in mapping.items()]
    return "\n".join(lines)


def _collection() -> chromadb.Collection:
    client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    return client.get_or_create_collection(
        name=OBSIDIAN_RAG_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )


def _load_state() -> dict[str, str]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict[str, str]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=True, indent=2), encoding="utf-8")


def _embed(text: str) -> list[float]:
    resp = requests.post(
        EMBED_URL,
        json={"model": OBSIDIAN_EMBED_MODEL, "prompt": text},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["embedding"]


def _chunk_markdown(text: str) -> list[str]:
    clean = text.replace("\r\n", "\n").strip()
    if not clean:
        return []

    blocks = [b.strip() for b in re.split(r"\n\s*\n", clean) if b.strip()]
    if not blocks:
        return [clean[:OBSIDIAN_CHUNK_SIZE]]

    chunks: list[str] = []
    current = ""

    for block in blocks:
        candidate = block if not current else f"{current}\n\n{block}"
        if len(candidate) <= OBSIDIAN_CHUNK_SIZE:
            current = candidate
            continue

        if current:
            chunks.append(current)
            if OBSIDIAN_CHUNK_OVERLAP > 0:
                overlap = current[-OBSIDIAN_CHUNK_OVERLAP :]
                current = f"{overlap}\n\n{block}" if overlap else block
            else:
                current = block
        else:
            # Oversized block: split hard
            start = 0
            while start < len(block):
                end = start + OBSIDIAN_CHUNK_SIZE
                chunks.append(block[start:end])
                start = end - OBSIDIAN_CHUNK_OVERLAP if OBSIDIAN_CHUNK_OVERLAP > 0 else end
            current = ""

    if current:
        chunks.append(current)

    return [c.strip() for c in chunks if c.strip()]


def _source_hash(path: Path) -> str:
    stat = path.stat()
    payload = f"{path.as_posix()}::{stat.st_mtime_ns}::{stat.st_size}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _delete_source_chunks(collection: chromadb.Collection, source: str) -> None:
    try:
        existing = collection.get(where={"source": source}, include=[])
        ids = existing.get("ids", [])
        if ids:
            collection.delete(ids=ids)
    except Exception:
        # Chroma where-filter support can vary by version; ignore hard failure.
        pass


def sync_obsidian_index() -> str:
    """Incrementally syncs vault markdown files into the local vector store."""
    vault = _vault_path()
    if not vault.exists() or not vault.is_dir():
        return (
            f"⚠️ Obsidian vault not found: {vault}. "
            "Set OBSIDIAN_VAULT_DIR in .env to enable vault indexing."
        )

    collection = _collection()
    old_state = _load_state()
    new_state: dict[str, str] = {}

    md_files = sorted(vault.rglob("*.md"))
    changed_count = 0

    for path in md_files:
        rel = path.relative_to(vault).as_posix()
        src_hash = _source_hash(path)
        new_state[rel] = src_hash

        if old_state.get(rel) == src_hash:
            continue

        changed_count += 1
        _delete_source_chunks(collection, rel)

        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue

        chunks = _chunk_markdown(text)
        if not chunks:
            continue

        embeddings: list[list[float]] = []
        ids: list[str] = []
        metadatas: list[dict] = []

        for idx, chunk in enumerate(chunks):
            try:
                emb = _embed(chunk)
            except Exception:
                continue

            embeddings.append(emb)
            ids.append(f"{rel}::chunk::{idx}::{uuid.uuid4()}")
            metadatas.append({"source": rel, "chunk_index": idx})

        if embeddings:
            collection.add(documents=chunks, embeddings=embeddings, metadatas=metadatas, ids=ids)

    removed = set(old_state.keys()) - set(new_state.keys())
    for rel in removed:
        _delete_source_chunks(collection, rel)

    _save_state(new_state)

    return (
        f"✅ Obsidian index synced. Files: {len(md_files)}, changed: {changed_count}, removed: {len(removed)}"
    )


def _query_chunks(query: str, n_results: int = 8) -> list[tuple[str, str, float]]:
    collection = _collection()
    if collection.count() == 0:
        return []

    q_emb = _embed(query)
    results = collection.query(
        query_embeddings=[q_emb],
        n_results=min(n_results, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]

    ranked: list[tuple[str, str, float]] = []
    for doc, meta, dist in zip(docs, metas, dists):
        source = str((meta or {}).get("source", "unknown.md"))
        ranked.append((source, doc, float(dist)))

    return ranked


def retrieve_relevant_context(query: str, top_k: int = OBSIDIAN_RAG_TOP_K) -> str:
    """Returns concise RAG context from the most relevant note snippets."""
    sync_obsidian_index()

    try:
        ranked = _query_chunks(query, n_results=max(8, top_k * 3))
    except Exception as e:
        return f"⚠️ Obsidian RAG retrieval failed: {type(e).__name__}: {e}"

    if not ranked:
        return ""

    selected: list[tuple[str, str, float]] = []
    seen_sources: set[str] = set()

    for source, doc, dist in ranked:
        if source in seen_sources:
            continue
        seen_sources.add(source)
        selected.append((source, doc, dist))
        if len(selected) >= top_k:
            break

    lines: list[str] = []
    total_chars = 0

    for source, doc, dist in selected:
        cleaned = re.sub(r"\s+", " ", doc).strip()
        snippet = cleaned[:320]
        line = f"- {source} (distance={dist:.3f}): {snippet}"
        if total_chars + len(line) > OBSIDIAN_RAG_MAX_CONTEXT_CHARS:
            break
        lines.append(line)
        total_chars += len(line)

    if not lines:
        return ""

    return "Relevant Obsidian context:\n" + "\n".join(lines)


def search_vault(query: str, top_k: int = OBSIDIAN_RAG_TOP_K) -> str:
    """Tool action: semantic vault search with short snippets."""
    sync_msg = sync_obsidian_index()

    try:
        ranked = _query_chunks(query, n_results=max(8, top_k * 4))
    except Exception as e:
        return f"❌ search_vault failed: {type(e).__name__}: {e}"

    if not ranked:
        return f"{sync_msg}\n\nNo relevant notes found for query: {query}"

    by_source: dict[str, tuple[str, float]] = {}
    for source, doc, dist in ranked:
        best = by_source.get(source)
        if best is None or dist < best[1]:
            by_source[source] = (doc, dist)

    sorted_hits = sorted(by_source.items(), key=lambda item: item[1][1])[:top_k]

    lines = [sync_msg, "", f"Top {len(sorted_hits)} relevant notes for: {query}"]
    for idx, (source, (doc, dist)) in enumerate(sorted_hits, start=1):
        snippet = re.sub(r"\s+", " ", doc).strip()[:260]
        lines.append(f"{idx}. {source} (distance={dist:.3f})")
        lines.append(f"   {snippet}")

    return "\n".join(lines)


def _safe_note_name(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_\-./ ]+", "", name).strip().replace(" ", "_")
    cleaned = cleaned.strip("./")
    return cleaned


def read_note(filename: str) -> str:
    """Tool action: read a specific markdown note from the vault."""
    vault = _vault_path()
    if not vault.exists():
        return f"❌ Obsidian vault not found: {vault}"

    candidates = _candidate_note_paths(vault, filename)
    if not candidates:
        return f"❌ Note not found: {filename}"

    note_path = candidates[0]
    if not _is_within(vault, note_path.resolve()):
        return "❌ SECURITY: Invalid note path."

    content = note_path.read_text(encoding="utf-8")
    return f"✅ Note read: {note_path.relative_to(vault)}\n\n{content}"


def append_to_note(filename: str, content: str) -> str:
    """Tool action: append content to an existing note (or create it).
    V2: Auto-touches last_accessed in YAML frontmatter."""
    vault = _vault_path()
    vault.mkdir(parents=True, exist_ok=True)

    safe_name = _safe_note_name(filename)
    if not safe_name:
        return "❌ Invalid filename."

    if not safe_name.lower().endswith(".md"):
        safe_name += ".md"

    note_path = (vault / safe_name).resolve()
    if not _is_within(vault, note_path):
        return "❌ SECURITY: Attempted write outside vault."

    if note_path.exists() and not note_path.is_file():
        return "❌ Target path is not a file."

    note_path.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    block = content.strip() or "(empty)"

    if note_path.exists():
        # Touch last_accessed in frontmatter
        text = note_path.read_text(encoding="utf-8")
        fm, body, has_fm = _split_frontmatter(text)
        if has_fm:
            mapping = _parse_frontmatter_map(fm)
            mapping["last_accessed"] = today
            new_fm = _render_frontmatter_map(mapping)
            text = f"---\n{new_fm}\n---\n{body}"
        
        text += f"\n\n{block}\n"
        note_path.write_text(text, encoding="utf-8")
    else:
        stem = Path(safe_name).stem
        payload = f"""---\npriority: high\nlast_accessed: {today}\n---\n# {stem}\n\n{block}\n"""
        note_path.write_text(payload, encoding="utf-8")

    sync_obsidian_index()
    return f"✅ Note appended: {note_path.relative_to(vault)}"


def update_frontmatter(filename: str, key: str, value: str) -> str:
    """Tool action: update or insert a frontmatter key-value pair."""
    vault = _vault_path()
    if not vault.exists():
        return f"❌ Obsidian vault not found: {vault}"

    candidates = _candidate_note_paths(vault, filename)
    if not candidates:
        return f"❌ Note not found: {filename}"

    note_path = candidates[0]
    if not key.strip():
        return "❌ Invalid key."

    text = note_path.read_text(encoding="utf-8")
    fm, body, has_fm = _split_frontmatter(text)

    if has_fm:
        mapping = _parse_frontmatter_map(fm)
        mapping[key.strip()] = value.strip()
        new_fm = _render_frontmatter_map(mapping)
        updated = f"---\n{new_fm}\n---\n{body.lstrip()}"
    else:
        new_fm = f"{key.strip()}: {value.strip()}"
        updated = f"---\n{new_fm}\n---\n\n{text.lstrip()}"

    note_path.write_text(updated, encoding="utf-8")
    sync_obsidian_index()
    return f"✅ Frontmatter updated: {note_path.relative_to(vault)} | {key.strip()}={value.strip()}"


def read_frontmatter_only(filename: str) -> str:
    """Tool action: read only note metadata/frontmatter."""
    vault = _vault_path()
    if not vault.exists():
        return f"❌ Obsidian vault not found: {vault}"

    candidates = _candidate_note_paths(vault, filename)
    if not candidates:
        return f"❌ Note not found: {filename}"

    note_path = candidates[0]
    text = note_path.read_text(encoding="utf-8")
    fm, _, has_fm = _split_frontmatter(text)
    if not has_fm:
        return f"ℹ️ No frontmatter: {note_path.relative_to(vault)}"

    return f"✅ Frontmatter read: {note_path.relative_to(vault)}\n\n---\n{fm}\n---"


def search_by_tag(tag: str, limit: int = 20) -> str:
    """Tool action: list notes containing a specific Obsidian/markdown tag."""
    vault = _vault_path()
    if not vault.exists():
        return f"❌ Obsidian vault not found: {vault}"

    normalized = tag.strip().lstrip("#")
    if not normalized:
        return "❌ Invalid tag."

    pattern = re.compile(rf"(^|\s)#{re.escape(normalized)}(?=\s|$|[.,;:!?])", flags=re.IGNORECASE)
    matched: list[str] = []

    for p in _iter_md_files(vault):
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        if pattern.search(text):
            matched.append(p.relative_to(vault).as_posix())
        if len(matched) >= limit:
            break

    if not matched:
        return f"No notes found with tag #{normalized}"

    lines = [f"Found {len(matched)} notes with tag #{normalized}:"]
    lines.extend(f"- {m}" for m in matched)
    return "\n".join(lines)


def get_outgoing_links(filename: str) -> str:
    """Tool action: list outgoing wiki/markdown links from a note."""
    vault = _vault_path()
    if not vault.exists():
        return f"❌ Obsidian vault not found: {vault}"

    candidates = _candidate_note_paths(vault, filename)
    if not candidates:
        return f"❌ Note not found: {filename}"

    note_path = candidates[0]
    text = note_path.read_text(encoding="utf-8")

    wiki_links = re.findall(r"\[\[([^\]|#]+)(?:#[^\]]+)?(?:\|[^\]]+)?\]\]", text)
    md_links = re.findall(r"\[[^\]]+\]\(([^)]+\.md)(?:#[^)]+)?\)", text)
    links = sorted({l.strip() for l in (wiki_links + md_links) if l.strip()})

    if not links:
        return f"No outgoing links in {note_path.relative_to(vault)}"

    lines = [f"Outgoing links from {note_path.relative_to(vault)}:"]
    lines.extend(f"- {l}" for l in links)
    return "\n".join(lines)


def get_backlinks(filename: str, limit: int = 50) -> str:
    """Tool action: list notes that link to the target note."""
    vault = _vault_path()
    if not vault.exists():
        return f"❌ Obsidian vault not found: {vault}"

    candidates = _candidate_note_paths(vault, filename)
    if not candidates:
        return f"❌ Note not found: {filename}"

    target = candidates[0]
    rel_target = target.relative_to(vault).as_posix()
    stem_target = target.stem
    name_target = target.name.lower()
    rel_target_lower = rel_target.lower()

    backlinks: list[str] = []

    for p in _iter_md_files(vault):
        if p.resolve() == target.resolve():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue

        wiki_links = re.findall(r"\[\[([^\]|#]+)(?:#[^\]]+)?(?:\|[^\]]+)?\]\]", text)
        md_links = re.findall(r"\[[^\]]+\]\(([^)]+\.md)(?:#[^)]+)?\)", text)
        stem_refs = {Path(x).stem.lower() for x in (wiki_links + md_links)}
        file_refs = {Path(x).name.lower() for x in md_links}
        path_refs = {x.strip().lower() for x in md_links}

        if stem_target.lower() in stem_refs or name_target in file_refs or rel_target_lower in path_refs:
            backlinks.append(p.relative_to(vault).as_posix())

        if len(backlinks) >= limit:
            break

    if not backlinks:
        return f"No backlinks found for {rel_target}"

    lines = [f"Backlinks to {rel_target}:"]
    lines.extend(f"- {b}" for b in sorted(backlinks))
    return "\n".join(lines)


def move_note(filename: str, new_folder: str) -> str:
    """Tool action: move a note to another folder in the vault."""
    vault = _vault_path()
    if not vault.exists():
        return f"❌ Obsidian vault not found: {vault}"

    candidates = _candidate_note_paths(vault, filename)
    if not candidates:
        return f"❌ Note not found: {filename}"

    source = candidates[0]
    safe_folder = _safe_note_name(new_folder)
    if not safe_folder:
        return "❌ Invalid new folder."

    target_dir = (vault / safe_folder).resolve()
    if not _is_within(vault, target_dir):
        return "❌ SECURITY: Invalid target folder."

    target_dir.mkdir(parents=True, exist_ok=True)
    target = (target_dir / source.name).resolve()

    if not _is_within(vault, target):
        return "❌ SECURITY: Invalid target path."

    shutil.move(str(source), str(target))
    sync_obsidian_index()
    return f"✅ Note moved: {source.relative_to(vault)} -> {target.relative_to(vault)}"


def open_in_obsidian(filename: str) -> str:
    """Tool action: open a specific note in the Obsidian desktop app via URI."""
    vault = _vault_path()
    if not vault.exists():
        return f"❌ Obsidian vault not found: {vault}"

    candidates = _candidate_note_paths(vault, filename)
    if not candidates:
        return f"❌ Note not found: {filename}"

    note_path = candidates[0]
    uri = "obsidian://open?path=" + quote(str(note_path))
    opened = webbrowser.open(uri)
    status = "triggered" if opened else "not-confirmed"
    return f"✅ Open in Obsidian request {status}: {note_path.relative_to(vault)}\nURI: {uri}"


def write_to_obsidian(title: str, content: str, folder: str = OBSIDIAN_CORRECTIONS_DIR) -> str:
    """Tool action: create/update a note in the Obsidian vault.
    V2: Auto-injects YAML frontmatter with priority and last_accessed."""
    vault = _vault_path()
    vault.mkdir(parents=True, exist_ok=True)

    safe_title = _safe_note_name(title)
    safe_folder = _safe_note_name(folder) or OBSIDIAN_CORRECTIONS_DIR

    if not safe_title:
        return "❌ Invalid title."

    if not safe_title.lower().endswith(".md"):
        safe_title += ".md"

    target_dir = (vault / safe_folder).resolve()
    if not _is_within(vault, target_dir):
        return "❌ SECURITY: Invalid target folder."
    target_dir.mkdir(parents=True, exist_ok=True)

    note_path = (target_dir / safe_title).resolve()
    if not _is_within(vault, note_path):
        return "❌ SECURITY: Attempted write outside vault."

    today = datetime.now().strftime("%Y-%m-%d")
    body = content.strip() or "(empty)"

    # V2: YAML frontmatter injection
    payload = f"""---\npriority: high\nlast_accessed: {today}\n---\n# {Path(safe_title).stem}\n\n{body}\n"""

    note_path.write_text(payload, encoding="utf-8")
    sync_obsidian_index()
    return f"✅ Note written: {note_path.relative_to(vault)}"


def log_reflection_failure(action: dict, error_result: str, user_request: str) -> ReflectionFailure:
    """Create a failure log note to support a self-reflection loop."""
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    action_name = action.get("action", "unknown")
    title = f"failure_{action_name}_{ts}"

    content = (
        "## Failure Record\n"
        f"- time: {datetime.now().isoformat()}\n"
        f"- user_request: {user_request}\n"
        f"- action: `{json.dumps(action, ensure_ascii=True)}`\n"
        f"- error: `{error_result[:1200]}`\n\n"
        "## Reflection\n"
        "- What went wrong: pending analysis\n"
        "- Correct approach: pending user/system correction\n"
    )

    write_to_obsidian(title=title, content=content, folder=OBSIDIAN_CORRECTIONS_DIR)

    return ReflectionFailure(
        timestamp=datetime.now().isoformat(),
        action=action,
        error_result=error_result,
        user_request=user_request,
    )


def log_reflection_correction(previous_failure: ReflectionFailure, correction_text: str) -> str:
    """Create a correction note after user feedback or successful retry."""
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    action_name = previous_failure.action.get("action", "unknown")
    title = f"correction_{action_name}_{ts}"

    content = (
        "## Correction Record\n"
        f"- linked_failure_time: {previous_failure.timestamp}\n"
        f"- old_action: `{json.dumps(previous_failure.action, ensure_ascii=True)}`\n"
        f"- old_error: `{previous_failure.error_result[:1000]}`\n\n"
        "## Learned Fix\n"
        f"{correction_text.strip()}\n"
    )

    return write_to_obsidian(title=title, content=content, folder=OBSIDIAN_CORRECTIONS_DIR)
