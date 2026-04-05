import re
from difflib import get_close_matches
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

ALLOWED_FILES = {"SOUL.md", "USER.md", "SKILL.md", "WISDOM.md"}

def _normalize_content(text: str) -> str:
    """Converts literal backslash-n sequences to real newlines."""
    return text.replace('\\n', '\n')

def _get_filepath(filename: str) -> Path:
    clean_name = Path(filename).name
    if clean_name not in ALLOWED_FILES:
        raise PermissionError(f"SECURITY VIOLATION: '{clean_name}' is not allowed. Only SOUL.md, USER.md, SKILL.md, and WISDOM.md memory files can be managed.")

    from config import OBSIDIAN_VAULT_DIR, VAULT_DIR_MEMORY
    vault_path = Path(OBSIDIAN_VAULT_DIR).expanduser().resolve()
    
    # V2 path (snake_case), fallback to legacy
    memory_dir = vault_path / VAULT_DIR_MEMORY
    if not memory_dir.exists():
        legacy = vault_path / "_Memory"
        if legacy.exists():
            memory_dir = legacy
        else:
            memory_dir.mkdir(parents=True, exist_ok=True)
    
    p = memory_dir / clean_name
    
    if not p.exists():
        fallback_p = BASE_DIR / clean_name
        if fallback_p.exists():
            return fallback_p
        raise FileNotFoundError(f"'{clean_name}' not found in Obsidian Memory or base directory!")
    return p


def _find_section(content: str, section_name: str):
    """Section header matching: normalize, exact match, prefix match.
    Returns: (match_object, actual_header_line) or (None, None)"""
    section_name = re.sub(r'^(\d+)\.\s*', r'\1 ', section_name).strip()

    pattern = rf"(## {re.escape(section_name)}\n.*?)(?=\n## |\Z)"
    m = re.search(pattern, content, flags=re.DOTALL)
    if m:
        header = f"## {section_name}"
        return m, header

    escaped = re.escape(section_name)
    pattern = rf"(## {escaped}[^\n]*\n.*?)(?=\n## |\Z)"
    m = re.search(pattern, content, flags=re.DOTALL)
    if m:
        header_match = re.match(rf"## {escaped}[^\n]*", m.group(1))
        header = header_match.group(0) if header_match else f"## {section_name}"
        return m, header

    headers = re.findall(r'^## (.+)$', content, re.MULTILINE)
    close = get_close_matches(section_name, headers, n=1, cutoff=0.6)
    if close:
        best = close[0]
        pattern = rf"(## {re.escape(best)}\n.*?)(?=\n## |\Z)"
        m = re.search(pattern, content, flags=re.DOTALL)
        if m:
            return m, f"## {best}"

    return None, None


def _list_sections(content: str) -> str:
    """Lists all section headers in the file."""
    headers = re.findall(r'^## .+$', content, re.MULTILINE)
    return "Available sections:\n" + "\n".join(f"  - '{h}'" for h in headers)

def append_to_memory(filename: str, section_name: str, new_content: str) -> str:
    try:
        if not section_name or not section_name.strip():
            path = _get_filepath(filename)
            content = path.read_text(encoding="utf-8")
            return f"\u274c Section not specified!\n{_list_sections(content)}"

        path = _get_filepath(filename)
        content = path.read_text(encoding="utf-8")

        match, header = _find_section(content, section_name)
        if not match:
            return f"\u274c '## {section_name}' not found.\n{_list_sections(content)}"

        normalized = _normalize_content(new_content).strip()
        section_text = match.group(0)

        for line in normalized.splitlines():
            clean = line.strip().lstrip('- ').strip()
            if clean and len(clean) > 10 and clean in section_text:
                return (f"❌ DUPLICATE: '{clean}' already exists in '{section_name}' section!\n"
                        f"Content already exists. Add something different.")

        new_section = section_text.rstrip() + f"\n{normalized}\n"
        updated = content[:match.start()] + new_section + content[match.end():]
        path.write_text(updated, encoding="utf-8")
        return f"\u2705 {filename}: '{section_name}' added to section."
    except Exception as e:
        return f"\u274c ERROR: {type(e).__name__} - {str(e)}"

def update_section(filename: str, section_name: str, new_content: str) -> str:
    try:
        path = _get_filepath(filename)
        content = path.read_text(encoding="utf-8")

        match, header = _find_section(content, section_name)
        if not match:
            return f"\u274c Error: '## {section_name}' not found.\n{_list_sections(content)}"

        new_section = header + "\n" + f"{_normalize_content(new_content)}\n"
        updated = content[:match.start()] + new_section + content[match.end():]
        path.write_text(updated, encoding="utf-8")
        return f"✅ {filename}: '{section_name}' section fully UPDATED."
    except Exception as e:
        return f"❌ ERROR: {type(e).__name__} - {str(e)}"

def read_section(filename: str, section_name: str) -> str:
    try:
        if not section_name or not section_name.strip():
            path = _get_filepath(filename)
            content = path.read_text(encoding="utf-8")
            return f"ERROR: Section not specified!\n{_list_sections(content)}\nMention which section you want to read."

        path = _get_filepath(filename)
        content = path.read_text(encoding="utf-8")

        match, header = _find_section(content, section_name)
        if not match:
            return f"\u274c Error: '## {section_name}' not found.\n{_list_sections(content)}"

        return f"[{filename} - {section_name}]:\n" + match.group(0).strip()
    except Exception as e:
        return f"❌ ERROR: {type(e).__name__} - {str(e)}"


def edit_line(filename: str, section_name: str, old_text: str, new_text: str) -> str:
    """Finds and replaces specific text within a section."""
    try:
        if not old_text or not old_text.strip():
            return "\u274c ERROR: 'old' text cannot be empty! Specify text to replace."
        if not new_text or not new_text.strip():
            return "\u274c ERROR: 'new' text cannot be empty! Specify new value."

        path = _get_filepath(filename)
        content = path.read_text(encoding="utf-8")

        match, header = _find_section(content, section_name)
        if not match:
            return f"\u274c '## {section_name}' not found.\n{_list_sections(content)}"

        section_text = match.group(0)
        if old_text not in section_text:
            return (f"❌ '{old_text}' not found in '{section_name}' section.\n"
                    f"Use memory_read first, then provide the EXACT text.\n"
                    f"Section contents:\n{section_text}")

        new_section = section_text.replace(old_text, _normalize_content(new_text), 1)
        updated = content[:match.start()] + new_section + content[match.end():]
        path.write_text(updated, encoding="utf-8")
        return f"✅ {filename}: '{old_text}' → '{new_text}' REPLACED in '{section_name}' section."
    except Exception as e:
        return f"\u274c ERROR: {type(e).__name__} - {str(e)}"


def delete_line(filename: str, section_name: str, text_to_delete: str) -> str:
    """Deletes a specific line or item from a section."""
    try:
        path = _get_filepath(filename)
        content = path.read_text(encoding="utf-8")

        match, header = _find_section(content, section_name)
        if not match:
            return f"\u274c '## {section_name}' not found.\n{_list_sections(content)}"

        section_text = match.group(0)
        if text_to_delete not in section_text:
            return (f"❌ '{text_to_delete}' not found in '{section_name}' section.\n"
                    f"Use memory_read first.\nSection contents:\n{section_text}")

        new_section = section_text.replace(text_to_delete, "", 1)
        new_section = re.sub(r'\n{3,}', '\n\n', new_section)
        updated = content[:match.start()] + new_section + content[match.end():]
        path.write_text(updated, encoding="utf-8")
        return f"✅ {filename}: '{text_to_delete}' DELETED from '{section_name}' section."
    except Exception as e:
        return f"\u274c ERROR: {type(e).__name__} - {str(e)}"
