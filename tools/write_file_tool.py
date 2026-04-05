"""
File Write Tool — Secure file writing (Path Sandbox)
"""
from pathlib import Path

from config import ALLOWED_DIRS

def is_path_allowed(file_path: Path) -> bool:
    """Check if file path is within allowed directories"""
    resolved = file_path.expanduser().resolve()
    
    for allowed_dir in ALLOWED_DIRS:
        allowed_resolved = Path(allowed_dir).expanduser().resolve()
        try:
            resolved.relative_to(allowed_resolved)
            return True
        except ValueError:
            continue
    
    return False


PROTECTED_FILES = {"SOUL.md", "USER.md", "SKILL.md"}


def write_file(path: str, content: str) -> str:
    """Secure file writing. Only writes to allowed directories."""
    try:
        file_path = Path(path).expanduser().resolve()
    except Exception as e:
        return f"❌ Invalid file path: {str(e)}"

    if file_path.name in PROTECTED_FILES:
        return (
            f"❌ SECURITY: '{file_path.name}' cannot be written with write_file!\n"
            f"This is a memory file. Use memory_append or memory_update to modify it.\n"
            f"Example: {{\"action\": \"memory_update\", \"file\": \"{file_path.name}\", "
            f"\"section\": \"Section Name\", \"new_content\": \"new_text content\"}}"
        )

    if not is_path_allowed(file_path):
        return (
            f"❌ SECURITY: '{path}' is not in allowed directories!\n\n"
            f"Allowed directories:\n" + 
            "\n".join(f"  - {d}" for d in ALLOWED_DIRS)
        )
    
    content_size = len(content.encode('utf-8'))
    size_mb = content_size / (1024 * 1024)
    MAX_SIZE_MB = 10
    
    if size_mb > MAX_SIZE_MB:
        return (
            f"❌ Content too large!\n"
            f"Size: {size_mb:.2f}MB\n"
            f"Maximum: {MAX_SIZE_MB}MB"
        )
    
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_path.write_text(content, encoding="utf-8")
        
        line_count = content.count('\n') + 1
        size_kb = content_size / 1024
        
        return (
            f"✅ File written: {file_path}\n"
            f"Size: {size_kb:.1f}KB\n"
            f"Line count: {line_count}\n"
            f"Character count: {len(content)}"
        )
    
    except PermissionError:
        return f"❌ File write permission denied: {file_path}"
    
    except OSError as e:
        if "Disk quota" in str(e) or "No space" in str(e):
            return f"❌ Disk full! {str(e)}"
        return f"❌ File system error: {str(e)}"
    
    except Exception as e:
        return f"❌ WRITE ERROR: {type(e).__name__}: {str(e)}"


def append_file(path: str, content: str) -> str:
    """File append content to end of file."""
    try:
        file_path = Path(path).expanduser().resolve()
    except Exception as e:
        return f"❌ Invalid file path: {str(e)}"

    if file_path.name in PROTECTED_FILES:
        return (
            f"❌ SECURITY: '{file_path.name}' cannot be modified with append_file!\n"
            f"This is a memory file. Use memory_append or memory_update to modify it."
        )
    
    if not is_path_allowed(file_path):
        return (
            f"❌ SECURITY: '{path}' is not in allowed directories!\n\n"
            f"Allowed directories:\n" + 
            "\n".join(f"  - {d}" for d in ALLOWED_DIRS)
        )
    
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(file_path, 'a', encoding='utf-8') as f:
            f.write(content)
        
        total_size = file_path.stat().st_size / 1024
        added_size = len(content.encode('utf-8')) / 1024
        
        return (
            f"✅ Content appended: {file_path}\n"
            f"Added: {added_size:.1f}KB\n"
            f"Total file size: {total_size:.1f}KB"
        )
    
    except Exception as e:
        return f"❌ APPEND ERROR: {type(e).__name__}: {str(e)}"

def edit_file(path: str, old_string: str, new_string: str) -> str:
    """Replaces old_string with new_string in a file safely."""
    try:
        file_path = Path(path).expanduser().resolve()
    except Exception as e:
        return f"❌ Invalid file path: {str(e)}"

    if file_path.name in PROTECTED_FILES:
        return (
            f"❌ SECURITY: '{file_path.name}' cannot be modified with edit_file!\n"
            f"This is a memory file. Use memory_edit to modify it."
        )
    
    if not is_path_allowed(file_path):
        return f"❌ SECURITY: '{path}' is not in allowed directories!"
        
    if not file_path.exists():
        return f"❌ File not found: {file_path}"
        
    try:
        content = file_path.read_text(encoding="utf-8")
        
        occurrences = content.count(old_string)
        if occurrences == 0:
            # Maybe it's a newline formatting issue? Offer a hint.
            return f"❌ The string you provided to replace was NOT FOUND in {file_path.name}. Tip: Ensure exact match including exact spaces and line breaks."
        elif occurrences > 1:
            return f"❌ Ambiguous edit: The exact old_string appears {occurrences} times in the file. Please provide a larger chunk of text that includes surrounding lines so the system can uniquely identify which segment to replace."
            
        new_content = content.replace(old_string, new_string)
        file_path.write_text(new_content, encoding="utf-8")
        
        return f"✅ File successfully patched: {file_path} (Replaced 1 occurrence of old_string)."
        
    except Exception as e:
        return f"❌ EDIT ERROR: {type(e).__name__}: {str(e)}"

if __name__ == "__main__":
    print("=== File Write Tool Test ===\n")
    print(write_file("/tmp/agent-workspace/test.txt", "Test content"))
    print(append_file("/tmp/agent-workspace/test.txt", "\nExtra line"))