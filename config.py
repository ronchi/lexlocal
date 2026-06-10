"""App-wide configuration and knowledge-base registry."""

import json
import re
from pathlib import Path

APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

KB_REGISTRY_FILE = DATA_DIR / "kb_registry.json"
SETTINGS_FILE     = DATA_DIR / "settings.json"
LANCEDB_DIR = str(DATA_DIR / "lancedb")
Path(LANCEDB_DIR).mkdir(exist_ok=True)

DEFAULT_OLLAMA_BASE = "http://localhost:11434"
DEFAULT_EMBED_MODEL = "nomic-embed-text"
DEFAULT_CHAT_MODEL  = "llama3.3:70b"

CHUNK_SIZE = 512
CHUNK_OVERLAP = 64

LEGAL_SYSTEM_PROMPT = """\
You are an expert legal assistant helping attorneys and pro se litigants analyze \
documents, conduct research, and draft legal materials. You reason carefully, cite \
sources from the provided context, and flag when you are uncertain. Always ground \
your answers in the retrieved documents; when context is insufficient, say so \
explicitly rather than speculating. Use plain language unless legal precision is \
required, and offer to clarify technical terms."""


def kb_table_name(kb_name: str) -> str:
    """Convert a KB name to a valid LanceDB table identifier."""
    return "kb_" + re.sub(r"[^a-z0-9]", "_", kb_name.lower())


def load_registry() -> dict:
    if KB_REGISTRY_FILE.exists():
        try:
            return json.loads(KB_REGISTRY_FILE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def save_registry(registry: dict) -> None:
    KB_REGISTRY_FILE.write_text(json.dumps(registry, indent=2))


def register_kb(name: str, folder: str) -> None:
    registry = load_registry()
    registry[name] = {"folder": folder, "indexed": False, "doc_count": 0}
    save_registry(registry)


def mark_kb_indexed(name: str, doc_count: int) -> None:
    registry = load_registry()
    if name in registry:
        registry[name]["indexed"] = True
        registry[name]["doc_count"] = doc_count
        save_registry(registry)


def remove_kb(name: str) -> None:
    registry = load_registry()
    registry.pop(name, None)
    save_registry(registry)


def rename_kb(old_name: str, new_name: str) -> None:
    """Rename a KB in the registry (does not touch LanceDB — caller must rename the table)."""
    registry = load_registry()
    if old_name not in registry:
        raise KeyError(f"KB '{old_name}' not found in registry.")
    if new_name in registry:
        raise ValueError(f"A KB named '{new_name}' already exists.")
    registry[new_name] = registry.pop(old_name)
    save_registry(registry)


# ---------------------------------------------------------------------------
# Persisted user settings
# ---------------------------------------------------------------------------

# Default prompt shown in the Summarizer tab.  Stored here so it is available
# to both the UI (for pre-filling) and the settings persistence helpers.
DEFAULT_SUMMARIZE_PROMPT = """\
You are a skilled legal analyst. Summarize the following document in \
well-structured Markdown.

Include these sections where applicable:

## Document Overview
Brief description of the document type, jurisdiction, and overall purpose.

## Parties Involved
List the principal parties and their roles.

## Key Facts
The most important factual elements of the document.

## Legal Issues or Claims
The legal questions raised, causes of action, or claims asserted.

## Arguments, Holdings, or Conclusions
The main arguments made, legal holdings, or conclusions reached.

## Important Dates & Deadlines
Any significant dates, filing deadlines, or time-sensitive provisions.

## Relief Sought or Outcome
What outcome is requested or was reached.

## Notable Provisions, Risks, or Action Items
Flag unusual clauses, potential risks, or items requiring immediate attention.\
"""

# Keys stored in settings.json and their built-in defaults.
_SETTINGS_DEFAULTS: dict = {
    "ollama_base":        DEFAULT_OLLAMA_BASE,
    "embed_model":        DEFAULT_EMBED_MODEL,
    "chat_model":         DEFAULT_CHAT_MODEL,
    "sum_model":          DEFAULT_CHAT_MODEL,  # Summarizer model (independent of Chat)
    "cl_api_token":       "",   # CourtListener API token — sensitive but local-only
    "summarize_prompt":   DEFAULT_SUMMARIZE_PROMPT,
    "chat_temperature":   0.1,  # Temperature for the Chat tab
    "sum_temperature":    0.1,  # Temperature for the Summarizer tab (independent)
}


def load_settings() -> dict:
    """
    Return persisted user settings, falling back to defaults for any missing key.
    Safe to call at import time; returns defaults if the file doesn't exist yet.
    """
    saved: dict = {}
    if SETTINGS_FILE.exists():
        try:
            saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            saved = {}
    # Merge: saved values win; missing keys get their default
    return {k: saved.get(k, v) for k, v in _SETTINGS_DEFAULTS.items()}


def save_settings(settings: dict) -> None:
    """
    Persist *settings* to disk, merging with defaults so unknown keys are
    never lost and missing keys are filled in.
    """
    merged = {k: settings.get(k, v) for k, v in _SETTINGS_DEFAULTS.items()}
    SETTINGS_FILE.write_text(
        json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8"
    )
