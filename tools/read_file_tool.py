"""
File Read Tool — Secure file reading with Pagination and AST support
"""
from pathlib import Path
import ast

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

def read_file(path: str, start_line: int = 1, end_line: int = 200) -> str:
    """Reads a file with pagination. Returns lines with line numbers."""
    try:
        file_path = Path(path).expanduser().resolve()
    except Exception as e:
        return f"❌ Invalid file path: {str(e)}"
    
    if not is_path_allowed(file_path):
        return (
            f"❌ SECURITY: '{path}' is not in allowed directories!\n\n"
            f"Allowed directories:\n" + "\n".join(f"  - {d}" for d in ALLOWED_DIRS)
        )
    
    if not file_path.exists():
        return f"❌ File not found: {file_path}"
    
    if not file_path.is_file():
        return f"❌ This is not a file (probably a directory): {file_path}"
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        total_lines = len(lines)
        
        # Validation for paging
        start_idx = max(1, start_line) - 1
        end_idx = min(total_lines, end_line)
        
        if start_idx >= total_lines:
            return f"⚠️ Requested starting line {start_line} is beyond file end (Total: {total_lines} lines)."
        
        chunk = lines[start_idx:end_idx]
        
        # Add line numbers
        numbered_chunk = []
        for i, line in enumerate(chunk, start=start_idx + 1):
            numbered_chunk.append(f"{i:4d} | {line.rstrip("\n")}")
        
        content = "\n".join(numbered_chunk)
        
        footer = ""
        if end_idx < total_lines:
            footer = f"\n\n... (File has {total_lines - end_idx} more lines. Use read_file with start_line={end_idx + 1} to continue reading)"
            
        return (
            f"✅ File read: {file_path} (Lines {start_idx+1}-{end_idx} of {total_lines})\n"
            f"\n{'='*60}\n{content}{footer}"
        )
        
    except UnicodeDecodeError:
        return f"❌ File is not in UTF-8 format! (Likely binary): {file_path}"
    except Exception as e:
        return f"❌ READ ERROR: {type(e).__name__}: {str(e)}"


def list_code_outline(path: str) -> str:
    """Parses a python file to extract AST outline (classes/functions/imports)"""
    try:
        file_path = Path(path).expanduser().resolve()
    except Exception as e:
        return f"❌ Invalid file path: {str(e)}"
    
    if not is_path_allowed(file_path):
        return f"❌ SECURITY: '{path}' is not in allowed directories!"
        
    if not file_path.exists():
        return f"❌ File not found: {file_path}"
        
    if not str(file_path).endswith('.py'):
        return f"❌ AST outline is only supported for Python (.py) files."

    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content)
        
        outline = [f"File: {file_path.name}\nAbstract Syntax Tree Outline:"]
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                outline.append(f"class {node.name} (line {node.lineno}):")
                for sub in node.body:
                    if isinstance(sub, ast.FunctionDef):
                        outline.append(f"  def {sub.name} (line {sub.lineno})")
            elif isinstance(node, ast.FunctionDef):
                outline.append(f"def {node.name} (line {node.lineno})")
            elif isinstance(node, ast.AsyncFunctionDef):
                outline.append(f"async def {node.name} (line {node.lineno})")
                
        if len(outline) == 1:
            outline.append("(No classes or functions found in this file)")
            
        return "\n".join(outline)
    except SyntaxError as e:
        return f"❌ Syntax Error in {file_path.name}: {e}"
    except Exception as e:
        return f"❌ AST ERROR: {e}"