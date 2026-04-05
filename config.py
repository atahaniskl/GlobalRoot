"""
Consciousness-First Dual-Pass Agent Architecture — Central Configuration
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
SMART_MODEL = os.environ.get("SMART_MODEL", "qwen3.5:4b")
USER_NAME = os.environ.get("USER_NAME", "User")
ASSISTANT_NAME = os.environ.get("ASSISTANT_NAME", "Assistant")
PLATFORM_TARGET = os.environ.get("PLATFORM_TARGET", "")

CONSCIOUSNESS_TEMP = 0.7      
EXECUTOR_TEMP = 0.1           
SUMMARY_TEMP = 0.3            

MAX_HISTORY_TOKENS = 6000     
SLIDING_WINDOW_SIZE = 10      
NUM_CTX = 8192                
NUM_PREDICT = 4096            

BASE_MAX_LOOPS = 8            
EXTENDED_MAX_LOOPS = 16       

_PLATFORM_TARGET_NORM = PLATFORM_TARGET.strip().lower()
_IS_WINDOWS_TARGET = (_PLATFORM_TARGET_NORM == "windows") or (os.name == "nt")

_DEFAULT_ALLOWED_DIRS_WINDOWS = [
    str(Path.home() / "Projects"),
    str(Path.home() / "Documents"),
    str(Path.home() / "Downloads"),
    str(Path(os.environ.get("TEMP", "C:\\temp")) / "agent-workspace"),
]

_DEFAULT_ALLOWED_DIRS_LINUX = [
    str(Path.home() / "Projects"),
    str(Path.home() / "Documents"),
    str(Path.home() / "local-agent-workspace"),
    "/tmp/agent-workspace",
    str(Path.home() / "Downloads"),
]

_DEFAULT_ALLOWED_DIRS = _DEFAULT_ALLOWED_DIRS_WINDOWS if _IS_WINDOWS_TARGET else _DEFAULT_ALLOWED_DIRS_LINUX

_ALLOWED_DIRS_RAW = os.environ.get("ALLOWED_DIRS", "")
_ALLOWED_DIRS_NORMALIZED = _ALLOWED_DIRS_RAW.replace("\n", os.pathsep).replace(",", os.pathsep).replace(";", os.pathsep)
ALLOWED_DIRS = [
    str(Path(p.strip()).expanduser())
    for p in _ALLOWED_DIRS_NORMALIZED.split(os.pathsep)
    if p.strip()
] or _DEFAULT_ALLOWED_DIRS

BANNED_COMMANDS = [
    "sudo", "su", "rm -rf /", "mkfs", "dd if=",
    "chmod 777", "chown root", "systemctl", "reboot",
    "shutdown", "poweroff", "pkill -9", "> /dev/sda",
    "wget", "curl -O", "git clone", "pip install",
    "del /f /s /q", "erase /f /s /q", "rmdir /s /q", "rd /s /q",
    "format ", "diskpart", "bcdedit", "reg delete", "cipher /w",
    "remove-item -recurse -force", "remove-item -force -recurse",
    "shutdown /s", "shutdown /r", "shutdown /f", "shutdown /p",
    "restart-computer", "stop-computer"
]

DANGEROUS_PATTERNS = [">/dev/", "> /dev/", "| dd ", "| mkfs", "| sudo", "|sudo"]

BASH_TIMEOUT = 30             
BASH_MAX_OUTPUT = 2000        

# Obsidian + RAG settings
OBSIDIAN_VAULT_DIR = os.environ.get("OBSIDIAN_VAULT_DIR", str(Path.home() / "Obsidian"))

CHROMA_PERSIST_DIR = str(Path(OBSIDIAN_VAULT_DIR).expanduser().resolve() / ".root_index")
CHROMA_COLLECTION = "root_memory"
MEMORY_TOP_K = 3

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
OWNER_CHAT_ID = int(os.environ.get("OWNER_CHAT_ID", "0"))

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
TAVILY_BASE_URL = os.environ.get("TAVILY_BASE_URL", "https://api.tavily.com")
TAVILY_TIMEOUT = int(os.environ.get("TAVILY_TIMEOUT", "20"))
OBSIDIAN_EMBED_MODEL = os.environ.get("OBSIDIAN_EMBED_MODEL", "nomic-embed-text")
OBSIDIAN_RAG_COLLECTION = os.environ.get("OBSIDIAN_RAG_COLLECTION", "obsidian_notes")
OBSIDIAN_RAG_TOP_K = int(os.environ.get("OBSIDIAN_RAG_TOP_K", "4"))
OBSIDIAN_RAG_MAX_CONTEXT_CHARS = int(os.environ.get("OBSIDIAN_RAG_MAX_CONTEXT_CHARS", "4000"))
OBSIDIAN_CHUNK_SIZE = int(os.environ.get("OBSIDIAN_CHUNK_SIZE", "900"))
OBSIDIAN_CHUNK_OVERLAP = int(os.environ.get("OBSIDIAN_CHUNK_OVERLAP", "120"))
OBSIDIAN_CORRECTIONS_DIR = os.environ.get("OBSIDIAN_CORRECTIONS_DIR", "correction_logs")

# ── V2 Neural Architecture: Directory Standards (snake_case) ──────────────
VAULT_DIR_MEMORY = "_memory"
VAULT_DIR_JOURNALS = "journals"
VAULT_DIR_NEURAL_GRAPH = "neural_graph"
VAULT_DIR_PROJECTS = "projects"
VAULT_DIR_ATOMIC_NOTES = "03_atomic_notes"
VAULT_DIR_MOCS = "04_mocs"

# ── Memory Decay Settings ─────────────────────────────────────────────────
MEMORY_DECAY_DAYS = int(os.environ.get("MEMORY_DECAY_DAYS", "60"))
MEMORY_DECAY_DEFAULT_PRIORITY = "active"
MEMORY_DECAY_ARCHIVED_PRIORITY = "archived"