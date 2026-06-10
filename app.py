"""
======================================================================

LexLocal — AI-powered legal document assistant.

This application enables the user to create knowledge bases that can 
be accessed via a web-interface for use as a RAG (retrieval augmented
generation) so that the user can "chat" with their documents with a 
language interface.  This application uses Ollama and models that are 
downloaded via Ollama.

    Run with:  python app.py

    For LAN access, run with:  python app.py --lan

Copyright, 2026 by Ronald L. Chichester

This application is distributed under the MIT license.
    
======================================================================
"""

import sys
import json
import queue
import socket
import subprocess
import threading
from pathlib import Path

import gradio as gr
import httpx

# Set after demo.launch() so URL-display handlers can read live URLs.
_demo_ref: gr.Blocks | None = None


def _pick_folder() -> str:
    """
    Open a native OS folder-picker dialog and return the chosen path.

    Runs tkinter in a subprocess so it gets its own main thread — required
    on macOS (and avoids any Gradio thread-safety issues on all platforms).
    Returns an empty string if the user cancels.
    """
    script = (
        "import tkinter as tk;"
        "from tkinter import filedialog;"
        "root = tk.Tk();"
        "root.wm_attributes('-topmost', True);"
        "root.deiconify();"        # briefly visible so macOS grants focus
        "root.lift();"
        "root.focus_force();"
        "root.update();"
        "root.withdraw();"         # now hide it — dialog inherits topmost
        "path = filedialog.askdirectory(parent=root, title='Select Knowledge Base Folder');"
        "root.destroy();"
        "print(path, end='')"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=120,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _pick_file() -> str:
    """
    Open a native OS file-picker dialog restricted to supported document types.
    Runs in a subprocess for the same reason as _pick_folder (macOS main-thread
    restriction).  Returns the chosen path, or an empty string on cancel.
    """
    script = (
        "import tkinter as tk;"
        "from tkinter import filedialog;"
        "root = tk.Tk();"
        "root.wm_attributes('-topmost', True);"
        "root.deiconify();"        # briefly visible so macOS grants focus
        "root.lift();"
        "root.focus_force();"
        "root.update();"
        "root.withdraw();"         # now hide it — dialog inherits topmost
        "path = filedialog.askopenfilename("
        "    parent=root,"
        "    title='Select Document to Summarize',"
        "    filetypes=["
        "        ('All supported', '*.pdf *.docx *.xlsx *.odt *.txt *.md'),"
        "        ('PDF files', '*.pdf'),"
        "        ('Word documents', '*.docx'),"
        "        ('Excel workbooks', '*.xlsx'),"
        "        ('OpenDocument Text', '*.odt'),"
        "        ('Text / Markdown', '*.txt *.md'),"
        "        ('All files', '*.*'),"
        "    ]"
        ");"
        "root.destroy();"
        "print(path, end='')"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=120,
        )
        return result.stdout.strip()
    except Exception:
        return ""


# Maximum characters sent to the LLM for summarisation.  Very large documents
# are truncated with a warning rather than silently failing with a context error.
_MAX_SUMMARY_CHARS = 120_000


def _extract_file_text(file_path: Path) -> tuple[str, str]:
    """
    Extract the full text of *file_path* using the same extractors as ingestion.
    Returns (text, info_message).  info_message describes any truncation or
    warnings; it is an empty string when everything went smoothly.
    """
    from rag.ingestion import _load_pdf, _load_office_doc, SUPPORTED_EXTENSIONS

    suffix = file_path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        return "", f"⚠ Unsupported file type '{suffix}'. Supported: {SUPPORTED_EXTENSIONS}"

    warnings: list[str] = []

    try:
        if suffix == ".pdf":
            text = _load_pdf(file_path, log=lambda m: warnings.append(m))
        else:
            text = _load_office_doc(file_path)
    except Exception as exc:
        return "", f"⚠ Could not read file: {exc}"

    if not text.strip():
        return "", "⚠ No text could be extracted from this file."

    info = ""
    if len(text) > _MAX_SUMMARY_CHARS:
        original_chars = len(text)
        text = text[:_MAX_SUMMARY_CHARS]
        info = (
            f"⚠ Document is very large ({original_chars:,} characters). "
            f"Only the first {_MAX_SUMMARY_CHARS:,} characters were sent to the model. "
            "Consider splitting the document or using a model with a larger context window."
        )

    return text, info


sys.path.insert(0, str(Path(__file__).parent))
from config import (
    DEFAULT_OLLAMA_BASE,
    DEFAULT_EMBED_MODEL,
    DEFAULT_CHAT_MODEL,
    DEFAULT_SUMMARIZE_PROMPT,
    load_registry,
    register_kb,
    remove_kb,
    rename_kb,
    load_settings,
    save_settings,
)
from agents.legal_agent import run_agent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_ollama_models(base_url: str = DEFAULT_OLLAMA_BASE) -> list[str]:
    """
    Fetch the list of models currently installed in the Ollama instance.
    Returns an empty list (not a fake default) so callers can distinguish
    "Ollama is unreachable" from "Ollama is running but has no models".
    """
    try:
        resp = httpx.get(f"{base_url}/api/tags", timeout=4)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        return sorted(models)
    except Exception:
        return []


def _validated_model(model: str, models: list[str]) -> str:
    """
    Return *model* if it is in the *models* list, otherwise return the first
    available model, or an empty string if Ollama has no models at all.
    """
    if model in models:
        return model
    return models[0] if models else ""


def _registry_to_table(registry: dict) -> list[list]:
    rows = []
    for name, info in registry.items():
        status = "✓ Indexed" if info.get("indexed") else "⏳ Not indexed"
        rows.append([name, info.get("folder", ""), status, info.get("doc_count", 0)])
    return rows


def _kb_choices(registry: dict) -> list[str]:
    return [name for name, info in registry.items() if info.get("indexed")]


# ---------------------------------------------------------------------------
# Ingestion thread
# ---------------------------------------------------------------------------

def _ingest_streaming(
    kb_name: str,
    folder: str,
    embed_model: str,
    ollama_base: str,
    log_q: "queue.Queue[str | None]",
    force_full: bool = False,
) -> None:
    """Run ingestion in a background thread; push each log line onto log_q.
    Puts None as a sentinel when done."""
    from rag.ingestion import ingest_folder

    def cb(msg: str):
        log_q.put(msg)

    try:
        ingest_folder(
            kb_name, folder, embed_model, ollama_base,
            progress_cb=cb, force_full=force_full,
        )
    except Exception as exc:
        log_q.put(f"✗ Ingestion failed: {exc}")
    finally:
        log_q.put(None)  # sentinel — signals completion to the UI generator


# ---------------------------------------------------------------------------
# Build the Gradio interface
# ---------------------------------------------------------------------------

def build_ui(lan_mode: bool = False) -> gr.Blocks:

    # Load persisted settings and validate the saved chat model against whatever
    # Ollama actually has installed right now.
    _settings         = load_settings()
    _ollama_models    = _get_ollama_models(_settings["ollama_base"])
    _active_model     = _validated_model(_settings["chat_model"], _ollama_models)
    _active_sum_model = _validated_model(_settings.get("sum_model", _settings["chat_model"]), _ollama_models)
    _chat_temperature = float(_settings.get("chat_temperature", 0.1))
    _sum_temperature  = float(_settings.get("sum_temperature",  0.1))

    # If the saved chat model no longer exists, update the settings file immediately
    # so the stale name is not written back on the next auto-save.
    if _active_model != _settings["chat_model"]:
        save_settings({**_settings, "chat_model": _active_model})
        _settings["chat_model"] = _active_model
    # Same validation for the summarizer model.
    if _active_sum_model != _settings.get("sum_model"):
        save_settings({**_settings, "sum_model": _active_sum_model})
        _settings["sum_model"] = _active_sum_model

    with gr.Blocks(title="LexLocal — Legal AI Assistant") as demo:

        gr.Markdown(
            "# ⚖ LexLocal — Legal AI Assistant\n"
            "A locally-running legal research assistant powered by Ollama. "
            "No data leaves your machine."
        )

        # Shared state: raw CourtListener search results list
        _cl_results_state = gr.State([])

        # No background timers for KB or URL — refreshes are triggered explicitly
        # after each mutating operation so the UI is never interrupted mid-scroll.

        # ================================================================
        # Tab 1 — Settings
        # ================================================================
        with gr.Tab("⚙ Settings"):

            with gr.Row():
                # ── Ollama ─────────────────────────────────────────────
                with gr.Column():
                    gr.Markdown("### 🦙 Ollama Server")
                    ollama_url = gr.Textbox(
                        label="Ollama Base URL",
                        value=_settings["ollama_base"],
                        placeholder="http://localhost:11434",
                    )
                    embed_model_box = gr.Textbox(
                        label="Embedding Model",
                        value=_settings["embed_model"],
                        info="Must be pulled in Ollama (e.g. nomic-embed-text)",
                    )
                    test_btn    = gr.Button("🔌 Test Connection", variant="secondary")
                    conn_status = gr.Markdown("")

                # ── CourtListener ───────────────────────────────────────
                with gr.Column():
                    gr.Markdown("### 🏛 CourtListener API")
                    gr.Markdown(
                        "CourtListener provides free access to millions of published court "
                        "opinions. An API token raises your rate limit and is **free** — "
                        "register at "
                        "[courtlistener.com/register](https://www.courtlistener.com/register/)."
                    )
                    cl_token = gr.Textbox(
                        label="CourtListener API Token  (optional)",
                        value=_settings["cl_api_token"],
                        placeholder="Token abc123def456…",
                        type="password",
                    )

            gr.Markdown("---")
            gr.Markdown("### 🌐 App URLs")
            if lan_mode:
                gr.Markdown(
                    "✅ **LAN mode is active.** "
                    "Share the URL below with colleagues on the same network — "
                    "anyone on the LAN can open it in their browser."
                )
            else:
                gr.Markdown(
                    "⚠️ **LAN mode is not enabled.** "
                    "The app is only accessible on *this machine*. "
                    "To allow other devices on the network to connect, "
                    "restart with:  \n"
                    "`python app.py --lan`"
                )
            with gr.Row():
                local_url_box = gr.Textbox(
                    label="Local / LAN URL" if lan_mode else "Local URL (this machine only)",
                    interactive=False, scale=4, buttons=["copy"],
                    placeholder="(loading…)",
                )
                refresh_url_btn = gr.Button("↺ Refresh", scale=1, size="sm")
            share_note = gr.Markdown("")

        # ================================================================
        # Tab 2 — Knowledge Bases
        # ================================================================
        with gr.Tab("📚 Knowledge Bases"):

            gr.Markdown("### Current Knowledge Bases")
            kb_table = gr.Dataframe(
                headers=["Name", "Folder", "Status", "Documents"],
                value=_registry_to_table(load_registry()),
                interactive=False,
                wrap=True,
            )

            with gr.Row():
                # ── Add KB ──────────────────────────────────────────────
                with gr.Column():
                    gr.Markdown("### ➕ Add Knowledge Base")
                    kb_name_input = gr.Textbox(
                        label="Knowledge Base Name",
                        placeholder="e.g. Johnson v Smith Case File",
                    )
                    with gr.Row():
                        kb_folder_input = gr.Textbox(
                            label="Folder Path",
                            placeholder="/Users/you/Documents/case-001",
                            scale=4,
                        )
                        browse_btn = gr.Button("📁 Browse…", scale=1, min_width=110)
                    with gr.Row():
                        add_btn    = gr.Button("Add KB (no index)", variant="secondary")
                        ingest_btn = gr.Button("Add + Ingest Now",  variant="primary")
                    ingest_log = gr.Textbox(
                        label="Ingestion Log",
                        lines=10, interactive=False,
                        elem_classes=["log-box"],
                    )

                # ── Modify KB ────────────────────────────────────────────
                with gr.Column():
                    gr.Markdown("### ✏ Modify a Knowledge Base")
                    modify_kb_dd = gr.Dropdown(
                        choices=list(load_registry().keys()),
                        label="Select Knowledge Base",
                        allow_custom_value=False,
                    )
                    with gr.Row():
                        reindex_btn = gr.Button("↺ Re-index", variant="primary", scale=1)
                        delete_btn  = gr.Button("🗑 Delete",   variant="stop",    scale=1)
                    force_full_chk = gr.Checkbox(
                        label="Force full re-index",
                        value=False,
                        info=(
                            "Unchecked = fast incremental (only new/changed files).  "
                            "Checked = drop table and re-embed everything from scratch "
                            "(use when switching embedding models)."
                        ),
                    )

                    gr.Markdown("#### ✏ Rename Knowledge Base")
                    with gr.Row():
                        rename_input = gr.Textbox(
                            label="New Name",
                            placeholder="Enter new KB name…",
                            scale=3,
                        )
                        rename_btn = gr.Button("✏ Rename", variant="secondary", scale=1)
                    rename_msg  = gr.Markdown("")
                    delete_msg  = gr.Markdown("")
                    reindex_log = gr.Textbox(
                        label="Re-index Log",
                        lines=10, interactive=False,
                        elem_classes=["log-box"],
                    )

            gr.Markdown("---")
            with gr.Row():
                view_log_btn = gr.Button("📋 View Ingestion Log File", size="sm")
                from config import DATA_DIR as _DATA_DIR
                gr.Markdown(
                    f"Log: `{_DATA_DIR}/ingestion.log`  "
                    "(tail it in a terminal for live output during long ingestions)"
                )
            log_viewer = gr.Textbox(
                label="ingestion.log (last 100 lines)",
                lines=12, interactive=False,
                elem_classes=["log-box"], visible=False,
            )

        # ================================================================
        # Tab 3 — CourtListener
        # ================================================================
        with gr.Tab("🏛 CourtListener"):

            gr.Markdown(
                "## 🏛 CourtListener — AI-Assisted Opinion Search\n"
                "Describe your legal research need in plain English and let the AI "
                "extract search parameters for you, or fill them in manually.  \n"
                "Select the opinions you want, then download and ingest them into any "
                "knowledge base in one step."
            )

            with gr.Row():
                # ── Left: AI description → parameters ───────────────────
                with gr.Column(scale=1):
                    gr.Markdown(
                        "### 🤖 Describe Your Research Need\n"
                        "Type what you are looking for in plain English. "
                        "The AI will extract a query, court filter, and date range "
                        "and pre-fill the search parameters for you."
                    )
                    cl_natural = gr.Textbox(
                        label="What are you looking for?",
                        placeholder=(
                            "e.g.  Recent 9th Circuit decisions about GPS tracking "
                            "devices and the automobile exception to the Fourth "
                            "Amendment, decided after 2018."
                        ),
                        lines=6,
                    )
                    cl_ai_btn    = gr.Button(
                        "🤖 Generate Search Parameters", variant="secondary"
                    )
                    cl_ai_status = gr.Markdown("")
                    gr.Markdown(
                        "_Uses whichever **Chat Model** is selected on the 💬 Chat tab. "
                        "Ollama must be running._"
                    )

                # ── Right: Search parameters (manual or AI-filled) ───────
                with gr.Column(scale=1):
                    gr.Markdown("### 🔎 Search Parameters")
                    cl_query = gr.Textbox(
                        label="Search Query",
                        placeholder=(
                            "e.g.  fourth amendment automobile exception "
                            "warrantless search"
                        ),
                        lines=2,
                    )
                    with gr.Row():
                        cl_semantic = gr.Checkbox(
                            label="Semantic (AI) search",
                            value=True,
                            info="Uncheck for exact keyword matching",
                            scale=1,
                        )
                        cl_page_size = gr.Slider(
                            minimum=5, maximum=1000, value=20, step=5,
                            label="Max results", scale=2,
                            info="Large values (>100) fetch multiple API pages and may take a moment.",
                        )
                    with gr.Row():
                        cl_court = gr.Textbox(
                            label="Court filter",
                            placeholder="scotus  ca9  nyed … (blank = all courts)",
                            scale=2,
                        )
                        cl_after  = gr.Textbox(
                            label="Opinion issued after",
                            placeholder="YYYY-MM-DD",
                            info="Date the opinion was issued by the court",
                            scale=1,
                        )
                        cl_before = gr.Textbox(
                            label="Opinion issued before",
                            placeholder="YYYY-MM-DD",
                            info="Date the opinion was issued by the court",
                            scale=1,
                        )
                    cl_search_btn = gr.Button(
                        "🔍 Search CourtListener", variant="primary"
                    )

            cl_search_status = gr.Markdown("")
            cl_query_sent = gr.Textbox(
                label="Query sent to CourtListener",
                interactive=False,
                placeholder="(URL will appear here after you click Search)",
                lines=2,
            )

            cl_results_table = gr.Dataframe(
                headers=["ID", "Case Name", "Court", "Date Issued", "Citations", "PDF?"],
                value=[],
                interactive=False,
                wrap=True,
                label="Search Results",
            )

            with gr.Row():
                cl_select_all_btn = gr.Button(
                    "☑ Select All",      size="sm", variant="secondary"
                )
                cl_clear_sel_btn  = gr.Button(
                    "☐ Clear Selection", size="sm", variant="secondary"
                )

            cl_checkboxes = gr.CheckboxGroup(
                choices=[],
                label="Select opinions to download",
                interactive=True,
            )

            gr.Markdown("---")
            gr.Markdown(
                "### 📥 Add Selected Opinions to a Knowledge Base\n"
                "Choose an **existing** KB to append documents to its folder (they "
                "will be indexed automatically), or select **— New KB —** to create "
                "a fresh knowledge base."
            )
            with gr.Row():
                cl_dest_dd = gr.Dropdown(
                    choices=["— New KB —"] + list(load_registry().keys()),
                    label="Destination Knowledge Base",
                    value="— New KB —",
                    scale=2,
                    allow_custom_value=False,
                    info=(
                        "Existing KB: documents are saved to a courtlistener/ "
                        "sub-folder and re-indexed automatically."
                    ),
                )
                cl_new_kb_name = gr.Textbox(
                    label="New KB name  (only when creating a new KB)",
                    placeholder="e.g.  4th Amendment Automobile Cases",
                    scale=2,
                )
            cl_download_btn = gr.Button(
                "⬇ Download Selected Opinions & Ingest into KB",
                variant="primary",
            )
            cl_log = gr.Textbox(
                label="Download / Ingestion Log",
                lines=14, interactive=False,
                elem_classes=["log-box"],
            )

        # ================================================================
        # Tab 4 — Chat
        # ================================================================
        with gr.Tab("💬 Chat"):

            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("### Session Settings")
                    chat_model_dd = gr.Dropdown(
                        choices=_ollama_models,
                        value=_active_model,
                        label="Chat Model",
                        allow_custom_value=True,
                    )
                    refresh_models_btn    = gr.Button("↺ Refresh Models", size="sm")
                    refresh_models_status = gr.Markdown("")
                    temperature_sl = gr.Slider(
                        minimum=0.0, maximum=2.0, value=_chat_temperature, step=0.05,
                        label="Temperature",
                        info="Lower = more deterministic; higher = more creative",
                    )

                    gr.Markdown("### Active Knowledge Bases")
                    kb_checkboxes = gr.CheckboxGroup(
                        choices=_kb_choices(load_registry()),
                        label="Select KBs for this conversation",
                        info="Only indexed KBs appear here",
                    )
                    chat_kb_refresh_btn = gr.Button(
                        "↺ Refresh KB List", size="sm", variant="secondary"
                    )
                    gr.Markdown("### Ollama URL")
                    chat_ollama_url = gr.Textbox(
                        label="", value=_settings["ollama_base"], show_label=False
                    )

                with gr.Column(scale=3):
                    chatbot = gr.Chatbot(
                        label="Legal Assistant",
                        height=540,
                        buttons=["copy", "copy_all"],
                        render_markdown=True,
                    )
                    with gr.Row():
                        msg_input = gr.Textbox(
                            placeholder=(
                                "Ask a question about your documents, request a draft, "
                                "or describe a legal task…"
                            ),
                            show_label=False, scale=5, lines=2,
                        )
                        send_btn = gr.Button("Send",    variant="primary", scale=1)
                        stop_btn = gr.Button("⏹ Stop", variant="stop",    scale=1,
                                             visible=False)
                    clear_btn = gr.Button("Clear Conversation", size="sm")

        # ================================================================
        # Event handlers
        # ================================================================

        # ── Tab 1: Settings ───────────────────────────────────────────────────

        def test_connection(base_url):
            models = _get_ollama_models(base_url)
            if models == [DEFAULT_CHAT_MODEL]:
                return "⚠ Could not reach Ollama — is it running?"
            return (
                f"✓ Connected. {len(models)} model(s) available: "
                f"{', '.join(models[:5])}"
            )

        test_btn.click(test_connection, inputs=[ollama_url], outputs=[conn_status])

        # ── Auto-save settings whenever any field on the Settings tab changes ──
        # Each handler receives the new value of its own field plus the current
        # values of the others so the full settings dict can be written atomically.

        # Each Settings-tab auto-save handler calls load_settings() first so it
        # always merges with the full current state (including summarize_prompt)
        # rather than overwriting keys it doesn't explicitly set.
        def _save_ollama_url(val, embed, token, chat_model):
            save_settings({**load_settings(), "ollama_base":  val,
                           "embed_model": embed, "cl_api_token": token,
                           "chat_model":  chat_model})

        def _save_embed_model(val, url, token, chat_model):
            save_settings({**load_settings(), "embed_model":  val,
                           "ollama_base": url, "cl_api_token": token,
                           "chat_model":  chat_model})

        def _save_cl_token(val, url, embed, chat_model):
            save_settings({**load_settings(), "cl_api_token": val,
                           "ollama_base": url, "embed_model":  embed,
                           "chat_model":  chat_model})

        def _save_chat_model(val, url, embed, token):
            save_settings({**load_settings(), "chat_model":   val,
                           "ollama_base": url, "embed_model":  embed,
                           "cl_api_token": token})

        ollama_url.change(
            _save_ollama_url,
            inputs=[ollama_url, embed_model_box, cl_token, chat_model_dd],
        )
        # Keep the Chat-tab Ollama URL mirror in sync with the Settings-tab value
        ollama_url.change(lambda v: v, inputs=[ollama_url], outputs=[chat_ollama_url])
        embed_model_box.change(
            _save_embed_model,
            inputs=[embed_model_box, ollama_url, cl_token, chat_model_dd],
        )
        cl_token.change(
            _save_cl_token,
            inputs=[cl_token, ollama_url, embed_model_box, chat_model_dd],
        )
        chat_model_dd.change(
            _save_chat_model,
            inputs=[chat_model_dd, ollama_url, embed_model_box, cl_token],
        )

        def _get_urls():
            local = ""
            if _demo_ref is not None:
                local = getattr(_demo_ref, "local_url", "") or ""
            if not local:
                try:
                    ip   = socket.gethostbyname(socket.gethostname())
                    port = (
                        getattr(_demo_ref, "server_port", None)
                        or getattr(_demo_ref, "port", None)
                        or 7860
                    )
                    local = f"http://{ip}:{port}"
                except Exception:
                    local = "(unavailable)"
            if lan_mode:
                note = "✅ LAN mode active — share the URL above with colleagues."
            else:
                note = "⚠️ LAN mode not active — restart with `python app.py --lan` to allow sharing with colleagues on your Local Area Network."
            return local, note

        refresh_url_btn.click(_get_urls, outputs=[local_url_box, share_note])
        # Populate URL once when the page loads — no repeating timer needed.
        demo.load(_get_urls, outputs=[local_url_box, share_note])

        # ── Tab 2: Knowledge Bases ────────────────────────────────────────────

        # Helper used by every KB-mutating operation to refresh all KB UI components.
        # Defined here so it is available to all handlers below.
        def _kb_refresh():
            """Return updated values for all KB-related UI components."""
            reg = load_registry()
            return (
                _registry_to_table(reg),
                gr.Dropdown(choices=list(reg.keys())),
                gr.CheckboxGroup(choices=_kb_choices(reg)),
                gr.Dropdown(choices=["— New KB —"] + list(reg.keys())),
            )

        _KB_OUTPUTS = [kb_table, modify_kb_dd, kb_checkboxes, cl_dest_dd]
        _KB_NOOP    = (gr.update(), gr.update(), gr.update(), gr.update())

        browse_btn.click(
            lambda: (
                (lambda p: gr.Textbox(value=p) if p else gr.Textbox())(_pick_folder())
            ),
            outputs=[kb_folder_input],
        )

        def add_kb(name, folder):
            name, folder = name.strip(), folder.strip()
            if not name or not folder:
                return ("⚠ Both name and folder are required.", *_KB_NOOP)
            if not Path(folder).exists():
                return (f"⚠ Folder not found: {folder}", *_KB_NOOP)
            register_kb(name, folder)
            return (f"✓ KB '{name}' registered (not yet indexed).", *_kb_refresh())

        add_btn.click(
            add_kb,
            inputs=[kb_name_input, kb_folder_input],
            outputs=[ingest_log, *_KB_OUTPUTS],
        )

        def add_and_ingest(name, folder, embed_model, ollama_base):
            name, folder = name.strip(), folder.strip()
            if not name or not folder:
                yield ("⚠ Both name and folder are required.", *_KB_NOOP)
                return
            if not Path(folder).exists():
                yield (f"⚠ Folder not found: {folder}", *_KB_NOOP)
                return
            register_kb(name, folder)
            yield (f"Registered '{name}'. Starting ingestion…\n", *_KB_NOOP)

            log_q: queue.Queue[str | None] = queue.Queue()
            threading.Thread(
                target=_ingest_streaming,
                args=(name, folder, embed_model, ollama_base, log_q),
                daemon=True,
            ).start()

            log_lines: list[str] = []
            while True:
                try:
                    msg = log_q.get(timeout=2)
                except queue.Empty:
                    yield ("\n".join(log_lines) + "\n⏳ working…", *_KB_NOOP)
                    continue
                if msg is None:
                    break
                log_lines.append(msg)
                yield ("\n".join(log_lines), *_KB_NOOP)
            # Final yield — refresh KB table/dropdowns now that indexing is done
            yield ("\n".join(log_lines) + "\n\n✅ Done — KB list updated.", *_kb_refresh())

        ingest_btn.click(
            add_and_ingest,
            inputs=[kb_name_input, kb_folder_input, embed_model_box, ollama_url],
            outputs=[ingest_log, *_KB_OUTPUTS],
        )

        def delete_kb_fn(name):
            if not name:
                return ("⚠ Select a KB first.", *_KB_NOOP)
            import lancedb as ldb
            from config import kb_table_name, LANCEDB_DIR
            try:
                ldb.connect(LANCEDB_DIR).drop_table(kb_table_name(name))
            except Exception:
                pass
            remove_kb(name)
            return (f"✓ KB '{name}' removed.", *_kb_refresh())

        delete_btn.click(
            delete_kb_fn,
            inputs=[modify_kb_dd],
            outputs=[delete_msg, *_KB_OUTPUTS],
        )

        def rename_kb_fn(old_name, new_name):
            old_name = (old_name or "").strip()
            new_name = (new_name or "").strip()
            _noop6 = (gr.update(), gr.update(), gr.update(), gr.update(), gr.update(), gr.update())
            if not old_name:
                return ("⚠ Select a KB first.", *_noop6)
            if not new_name:
                return ("⚠ Enter a new name.", *_noop6)
            if old_name == new_name:
                return ("⚠ New name is the same as the current name.", *_noop6)
            import lancedb as ldb
            from config import kb_table_name, LANCEDB_DIR
            try:
                rename_kb(old_name, new_name)
            except (KeyError, ValueError) as exc:
                return (f"⚠ {exc}", *_noop6)
            # Rename the LanceDB table so existing vectors remain accessible
            try:
                db      = ldb.connect(LANCEDB_DIR)
                old_tbl = kb_table_name(old_name)
                new_tbl = kb_table_name(new_name)
                if old_tbl in db.table_names():
                    db.rename_table(old_tbl, new_tbl)
            except Exception as exc:
                reg = load_registry()
                return (
                    f"✓ Registry renamed, but LanceDB table rename failed: {exc}. "
                    "The KB will need to be re-indexed before use.",
                    gr.Dropdown(choices=list(reg.keys()), value=new_name),
                    gr.Textbox(value=""),
                    *_kb_refresh(),
                )
            reg = load_registry()
            return (
                f"✓ KB renamed '{old_name}' → '{new_name}'.",
                gr.Dropdown(choices=list(reg.keys()), value=new_name),
                gr.Textbox(value=""),
                *_kb_refresh(),
            )

        rename_btn.click(
            rename_kb_fn,
            inputs=[modify_kb_dd, rename_input],
            outputs=[rename_msg, modify_kb_dd, rename_input, *_KB_OUTPUTS],
        )

        def reindex_kb_fn(name, embed_model, ollama_base, force_full):
            if not name:
                yield ("⚠ Select a KB first.", *_KB_NOOP)
                return
            registry = load_registry()
            if name not in registry:
                yield (f"⚠ KB '{name}' not found in registry.", *_KB_NOOP)
                return
            folder = registry[name]["folder"]
            mode   = "full rebuild" if force_full else "incremental"
            yield (f"Starting {mode} re-index of '{name}'…\n", *_KB_NOOP)

            log_q: queue.Queue[str | None] = queue.Queue()
            threading.Thread(
                target=_ingest_streaming,
                args=(name, folder, embed_model, ollama_base, log_q, force_full),
                daemon=True,
            ).start()

            log_lines: list[str] = []
            while True:
                try:
                    msg = log_q.get(timeout=2)
                except queue.Empty:
                    yield ("\n".join(log_lines) + "\n⏳ working…", *_KB_NOOP)
                    continue
                if msg is None:
                    break
                log_lines.append(msg)
                yield ("\n".join(log_lines), *_KB_NOOP)
            # Final yield — refresh KB table now that re-index is complete
            yield ("\n".join(log_lines) + "\n\n✅ Done — KB list updated.", *_kb_refresh())

        reindex_btn.click(
            reindex_kb_fn,
            inputs=[modify_kb_dd, embed_model_box, ollama_url, force_full_chk],
            outputs=[reindex_log, *_KB_OUTPUTS],
        )

        def view_log():
            from config import DATA_DIR as _D
            p = _D / "ingestion.log"
            if not p.exists():
                return gr.Textbox(value="(log file not yet created)", visible=True)
            tail = "\n".join(p.read_text(errors="replace").splitlines()[-100:])
            return gr.Textbox(value=tail, visible=True)

        view_log_btn.click(view_log, outputs=[log_viewer])

        # Manual refresh button on the Chat tab
        chat_kb_refresh_btn.click(_kb_refresh, outputs=_KB_OUTPUTS)

        # Populate KB list once when the page loads
        demo.load(_kb_refresh, outputs=_KB_OUTPUTS)

        # ── Tab 3: CourtListener ──────────────────────────────────────────────

        def cl_generate_params(description, chat_model, ollama_base):
            """
            Call the local LLM to extract structured CourtListener search parameters
            from a plain-English research description.
            Uses whichever chat model is currently selected on the Chat tab.
            """
            description = description.strip()
            if not description:
                return "", "", "", "", True, "⚠ Enter a description first."
            try:
                from langchain_ollama import ChatOllama
                llm = ChatOllama(model=chat_model, base_url=ollama_base, temperature=0)
                prompt = (
                    "You are a legal research assistant helping a lawyer search the "
                    "CourtListener case-law database.\n"
                    "Extract structured search parameters from the description below.\n"
                    "Return ONLY a single valid JSON object — no explanation, no markdown "
                    "code fences, no extra text whatsoever.\n\n"
                    "Required JSON fields:\n"
                    '  "query"        — concise search string for CourtListener\n'
                    '  "court"        — CourtListener court slug (scotus, ca9, nyed, …) '
                    'or "" for all courts\n'
                    '  "filed_after"  — YYYY-MM-DD or "" (date the opinion was issued)\n'
                    '  "filed_before" — YYYY-MM-DD or "" (date the opinion was issued)\n'
                    '  "semantic"     — true for conceptual/semantic search, '
                    'false for exact keyword matching\n\n'
                    f"Description: {description}\n\nJSON:"
                )
                response = llm.invoke(prompt)
                text  = response.content if hasattr(response, "content") else str(response)
                start = text.find("{")
                end   = text.rfind("}")
                if start == -1 or end <= start:
                    return (
                        "", "", "", "", True,
                        "⚠ The model did not return valid JSON. "
                        "Please fill in the search parameters manually.",
                    )
                params   = json.loads(text[start : end + 1])
                query    = str(params.get("query", ""))
                court    = str(params.get("court", ""))
                after    = str(params.get("filed_after", ""))
                before   = str(params.get("filed_before", ""))
                semantic = bool(params.get("semantic", True))
                status = (
                    "✓ Parameters extracted — review and adjust if needed, "
                    "then click **🔍 Search CourtListener**."
                )
                return query, court, after, before, semantic, status
            except Exception as exc:
                return (
                    "", "", "", "", True,
                    f"⚠ Could not reach Ollama ({chat_model} @ {ollama_base}): {exc}",
                )

        # cl_ai_btn uses chat_model_dd (defined in Tab 4) — Gradio allows
        # cross-tab component references within the same Blocks context.
        cl_ai_btn.click(
            cl_generate_params,
            inputs=[cl_natural, chat_model_dd, ollama_url],
            outputs=[cl_query, cl_court, cl_after, cl_before, cl_semantic, cl_ai_status],
        )

        def cl_do_search(query, token, semantic, court, after, before, page_size):
            from agents.courtlistener_agent import (
                search_opinions, format_results_table, make_checkbox_choices,
                CL_SEARCH, CL_CLUSTERS, CL_DOCKETS,
            )
            import urllib.parse

            query = query.strip()
            if not query and not court.strip() and not after.strip() and not before.strip():
                return (
                    [], [],
                    gr.CheckboxGroup(choices=[], value=[]),
                    "⚠ Enter a search query or at least one filter (court, date range).",
                    "",
                )

            # ── Build a human-readable representation of what will be sent ───
            has_query = bool(query)
            if has_query:
                display_params: dict = {
                    "q":         query,
                    "type":      "o",
                    "order_by":  "score desc",
                    "highlight": "on",
                    "page_size": 50,
                }
                if semantic:
                    display_params["semantic"] = "true"
                if court.strip():
                    display_params["court"] = court.strip()
                if after.strip():
                    display_params["filed_after"] = after.strip()
                if before.strip():
                    display_params["filed_before"] = before.strip()
                base_url = CL_SEARCH
                query_sent = base_url + "?" + urllib.parse.urlencode(
                    display_params, quote_via=urllib.parse.quote
                )
            else:
                display_params = {"page_size": 50}
                if after.strip():
                    display_params["date_filed__gte"] = after.strip()
                if before.strip():
                    display_params["date_filed__lte"] = before.strip()
                base_url = CL_CLUSTERS
                query_sent = base_url + "?" + urllib.parse.urlencode(
                    display_params, quote_via=urllib.parse.quote
                )
                if court.strip():
                    query_sent += (
                        f"\n(Court '{court.strip()}' applied client-side via "
                        f"{CL_DOCKETS}?court={urllib.parse.quote(court.strip())})"
                    )

            try:
                data    = search_opinions(
                    query, token, bool(semantic),
                    court, after, before, int(page_size),
                )
                results = data.get("results", [])
                raw_count = data.get("count", len(results))
                if isinstance(raw_count, int):
                    total = raw_count
                elif isinstance(raw_count, str) and raw_count.startswith("http"):
                    try:
                        import httpx as _httpx
                        _s = load_settings()
                        _h = {}
                        if _s.get("cl_api_token", "").strip():
                            _h["Authorization"] = f"Token {_s['cl_api_token'].strip()}"
                        _cr = _httpx.get(raw_count, headers=_h, timeout=10)
                        total = int(_cr.json().get("count", len(results)))
                    except Exception:
                        total = len(results)
                else:
                    total = int(raw_count or len(results))
                table   = format_results_table(results)
                choices = make_checkbox_choices(results)
                mode    = "semantic" if semantic else "keyword"
                status  = (
                    f"✓ **{total:,}** opinion(s) matched ({mode} search) — "
                    f"showing top **{len(results)}**."
                )
                return (results, table,
                        gr.CheckboxGroup(choices=choices, value=[]),
                        status, query_sent)
            except Exception as exc:
                return (
                    [],
                    [["", f"Search error: {exc}", "", "", "", ""]],
                    gr.CheckboxGroup(choices=[], value=[]),
                    f"✗ {exc}",
                    query_sent,
                )

        cl_search_btn.click(
            cl_do_search,
            inputs=[cl_query, cl_token, cl_semantic, cl_court,
                    cl_after, cl_before, cl_page_size],
            outputs=[_cl_results_state, cl_results_table, cl_checkboxes,
                     cl_search_status, cl_query_sent],
        )

        def cl_select_all_fn(results):
            from agents.courtlistener_agent import make_checkbox_choices
            c = make_checkbox_choices(results)
            return gr.CheckboxGroup(choices=c, value=c)

        def cl_clear_sel_fn(results):
            from agents.courtlistener_agent import make_checkbox_choices
            c = make_checkbox_choices(results)
            return gr.CheckboxGroup(choices=c, value=[])

        cl_select_all_btn.click(
            cl_select_all_fn, inputs=[_cl_results_state], outputs=[cl_checkboxes]
        )
        cl_clear_sel_btn.click(
            cl_clear_sel_fn, inputs=[_cl_results_state], outputs=[cl_checkboxes]
        )

        def cl_download_and_ingest(
            selected, results, dest_kb, new_kb_name,
            token, embed_model, ollama_base,
        ):
            from agents.courtlistener_agent import download_opinions
            from config import DATA_DIR as _DD

            if not selected:
                yield "⚠ Select at least one opinion to download."
                return

            registry = load_registry()
            is_existing_kb = dest_kb and dest_kb != "— New KB —" and dest_kb in registry
            if is_existing_kb:
                kb_name    = dest_kb
                kb_folder  = registry[dest_kb]["folder"]   # full KB root (for re-index)
                dest_path  = Path(kb_folder) / "courtlistener"  # download sub-folder
            else:
                kb_name = new_kb_name.strip()
                if not kb_name:
                    yield "⚠ Enter a name for the new Knowledge Base."
                    return
                kb_folder  = str(_DD / "courtlistener_downloads" / kb_name)
                dest_path  = Path(kb_folder)

            log_q: queue.Queue[str | None] = queue.Queue()

            def _thread():
                def cb(m: str): log_q.put(m)
                try:
                    cb(
                        f"── Phase 1: Downloading {len(selected)} opinion(s) "
                        f"→ {dest_path} …"
                    )
                    files = download_opinions(results, selected, dest_path, token, cb)
                    if not files:
                        cb(
                            "✗ No files downloaded — check URLs, token, "
                            "or network connection."
                        )
                        log_q.put(None)
                        return
                    if is_existing_kb:
                        cb(
                            f"\n── Phase 2: Adding {len(files)} file(s) to existing "
                            f"KB '{kb_name}' and re-indexing from {kb_folder} …"
                        )
                        # Re-index the FULL KB folder so existing docs stay intact
                        # and only the new files are added (incremental indexing).
                        _ingest_streaming(
                            kb_name, kb_folder, embed_model, ollama_base, log_q
                        )
                    else:
                        cb(f"\n── Phase 2: Registering new KB '{kb_name}'…")
                        register_kb(kb_name, kb_folder)
                        cb(
                            f"── Phase 3: Ingesting {len(files)} file(s) "
                            f"into KB '{kb_name}'…"
                        )
                        _ingest_streaming(
                            kb_name, kb_folder, embed_model, ollama_base, log_q
                        )
                except Exception as exc:
                    log_q.put(f"✗ Error: {exc}")
                    log_q.put(None)

            threading.Thread(target=_thread, daemon=True).start()

            yield (f"Starting download of {len(selected)} opinion(s)…\n", *_KB_NOOP)
            log_lines: list[str] = []
            while True:
                try:
                    msg = log_q.get(timeout=2)
                except queue.Empty:
                    yield ("\n".join(log_lines) + "\n⏳ working…", *_KB_NOOP)
                    continue
                if msg is None:
                    break
                log_lines.append(msg)
                yield ("\n".join(log_lines), *_KB_NOOP)
            # Final yield — refresh KB table now that download + ingest is complete
            yield ("\n".join(log_lines) + "\n\n✅ Done — KB list updated.", *_kb_refresh())

        cl_download_btn.click(
            cl_download_and_ingest,
            inputs=[
                cl_checkboxes, _cl_results_state,
                cl_dest_dd, cl_new_kb_name,
                cl_token, embed_model_box, ollama_url,
            ],
            outputs=[cl_log, *_KB_OUTPUTS],
        )

        # ── Tab 4: Chat ───────────────────────────────────────────────────────

        def refresh_models(ollama_base, current_model):
            """
            Re-query Ollama for installed models, update the dropdown choices,
            and fix the selected value if the previously-chosen model is gone.
            Uses the Settings-tab Ollama URL as the authoritative source.
            """
            models    = _get_ollama_models(ollama_base)
            new_value = _validated_model(current_model, models)
            if not models:
                status = "⚠ Could not reach Ollama — is it running?"
            elif new_value != current_model:
                status = (
                    f"✓ {len(models)} model(s) found.  "
                    f"'{current_model}' no longer exists — switched to '{new_value}'."
                )
            else:
                status = f"✓ {len(models)} model(s) available."
            # Persist the (possibly corrected) model choice
            save_settings({**load_settings(), "chat_model": new_value})
            return gr.Dropdown(choices=models, value=new_value), status

        refresh_models_btn.click(
            refresh_models,
            inputs=[ollama_url, chat_model_dd],
            outputs=[chat_model_dd, refresh_models_status],
        )

        _btn_running = (gr.update(visible=False), gr.update(visible=True))
        _btn_idle    = (gr.update(visible=True),  gr.update(visible=False))

        def chat(user_msg, history, kb_names, chat_model, temperature, ollama_base):
            if not user_msg.strip():
                yield history, "", *_btn_idle
                return
            history = history or []
            history.append({"role": "user",     "content": user_msg})
            history.append({"role": "assistant", "content": "_⏳ Thinking…_"})
            yield history, "", *_btn_running
            response = ""
            try:
                for chunk in run_agent(
                    user_msg, chat_model, temperature,
                    kb_names or [], DEFAULT_EMBED_MODEL, ollama_base,
                ):
                    response += chunk
                    history[-1]["content"] = response
                    yield history, "", *_btn_running
            except Exception as exc:
                history[-1]["content"] = f"⚠ Error: {exc}"
            yield history, "", *_btn_idle

        _chat_inputs  = [msg_input, chatbot, kb_checkboxes,
                         chat_model_dd, temperature_sl, chat_ollama_url]
        _chat_outputs = [chatbot, msg_input, send_btn, stop_btn]

        chat_run = send_btn.click(chat, inputs=_chat_inputs, outputs=_chat_outputs)
        submit_run = msg_input.submit(chat, inputs=_chat_inputs, outputs=_chat_outputs)
        stop_btn.click(fn=None, cancels=[chat_run, submit_run])
        clear_btn.click(lambda: ([], ""), outputs=[chatbot, msg_input])

        # ================================================================
        # Tab 5 — Summarizer
        # ================================================================
        with gr.Tab("📝 Summarizer"):

            gr.Markdown(
                "## 📝 Document Summarizer\n"
                "Select any document on your filesystem, review or adjust the "
                "summarization prompt, then click **Summarize**. "
                "The result is rendered as Markdown and can be copied to the clipboard."
            )

            with gr.Row():
                # ── Left column: controls ────────────────────────────────
                with gr.Column(scale=1):
                    gr.Markdown("### 📄 Document")
                    with gr.Row():
                        sum_file_input = gr.Textbox(
                            label="File Path",
                            placeholder="/Users/you/Documents/complaint.pdf",
                            scale=4,
                        )
                        sum_browse_btn = gr.Button("📄 Browse…", scale=1, min_width=110)

                    sum_file_info = gr.Markdown("")   # shows word count / warnings

                    gr.Markdown("### 🤖 Model")
                    sum_model_dd = gr.Dropdown(
                        choices=_ollama_models,
                        value=_active_sum_model,
                        label="Ollama Model",
                        allow_custom_value=True,
                        info="Uses the Ollama URL from the ⚙ Settings tab.",
                    )
                    sum_temperature_sl = gr.Slider(
                        minimum=0.0, maximum=2.0, value=_sum_temperature, step=0.05,
                        label="Temperature",
                        info="Lower = more deterministic; higher = more creative. "
                             "Saved separately from the Chat tab temperature.",
                    )

                    gr.Markdown("### 📋 Summarization Prompt")
                    gr.Markdown(
                        "This prompt is sent to the model along with the document "
                        "text. Edit it to change the style or focus of the summary. "
                        "Changes are **saved automatically** for future sessions."
                    )
                    sum_prompt = gr.Textbox(
                        label="Prompt",
                        value=_settings["summarize_prompt"],
                        lines=16,
                        max_lines=40,
                    )
                    sum_reset_btn = gr.Button(
                        "↺ Reset to Default Prompt", size="sm", variant="secondary"
                    )

                    with gr.Row():
                        sum_btn      = gr.Button("📝 Summarize", variant="primary",  scale=3)
                        sum_stop_btn = gr.Button("⏹ Stop",       variant="stop",     scale=1,
                                                 visible=False)
                        sum_clear    = gr.Button("🗑 Clear",     variant="secondary", scale=1)

                # ── Right column: output ─────────────────────────────────
                with gr.Column(scale=2):
                    sum_chatbot = gr.Chatbot(
                        label="Summary",
                        height=680,
                        buttons=["copy", "copy_all"],
                        render_markdown=True,
                        show_label=True,
                    )

        # ================================================================
        # Summarizer event handlers
        # ================================================================

        sum_browse_btn.click(
            lambda: (
                (lambda p: gr.Textbox(value=p) if p else gr.Textbox())(_pick_file())
            ),
            outputs=[sum_file_input],
        )

        def _sum_save_prompt(prompt_text):
            """Auto-save the summarization prompt whenever the user edits it."""
            save_settings({**load_settings(), "summarize_prompt": prompt_text})

        sum_prompt.change(_sum_save_prompt, inputs=[sum_prompt])

        def _sum_reset_prompt():
            save_settings({**load_settings(), "summarize_prompt": DEFAULT_SUMMARIZE_PROMPT})
            return gr.Textbox(value=DEFAULT_SUMMARIZE_PROMPT)

        sum_reset_btn.click(_sum_reset_prompt, outputs=[sum_prompt])

        def _sum_save_model(model_name):
            save_settings({**load_settings(), "sum_model": model_name})

        sum_model_dd.change(_sum_save_model, inputs=[sum_model_dd])

        def _save_chat_temperature(val):
            save_settings({**load_settings(), "chat_temperature": val})

        temperature_sl.change(_save_chat_temperature, inputs=[temperature_sl])

        def _save_sum_temperature(val):
            save_settings({**load_settings(), "sum_temperature": val})

        sum_temperature_sl.change(_save_sum_temperature, inputs=[sum_temperature_sl])

        def summarize(file_path_str, prompt, model, temperature, ollama_base, history):
            """
            Extract text from the selected file and stream a summary from the LLM.
            Yields updated history on every token so the output appears live.
            """
            from langchain_ollama import ChatOllama

            _sbn_run  = (gr.update(visible=False), gr.update(visible=True))
            _sbn_idle = (gr.update(visible=True),  gr.update(visible=False))

            file_path_str = (file_path_str or "").strip()
            if not file_path_str:
                yield history or [], "⚠ Select a file first.", *_sbn_idle
                return

            file_path = Path(file_path_str)
            if not file_path.exists():
                yield history or [], f"⚠ File not found: {file_path_str}", *_sbn_idle
                return

            history = list(history or [])

            # ── Extract text ──────────────────────────────────────────────
            yield (
                history + [
                    {"role": "user",      "content": f"📄 Summarize: `{file_path.name}`"},
                    {"role": "assistant", "content": "_⏳ Extracting text…_"},
                ],
                "",
                *_sbn_run,
            )

            text, info = _extract_file_text(file_path)
            if not text:
                history.append({"role": "user",      "content": f"📄 Summarize: `{file_path.name}`"})
                history.append({"role": "assistant",  "content": info or "⚠ No text extracted."})
                yield history, info, *_sbn_idle
                return

            word_count = len(text.split())
            char_count = len(text)
            file_info  = f"✓ `{file_path.name}` — {word_count:,} words  ({char_count:,} chars)"
            if info:
                file_info += f"\n\n{info}"

            history.append({"role": "user", "content": f"📄 Summarize: `{file_path.name}`"})
            history.append({"role": "assistant", "content": "_⏳ Sending to model…_"})
            yield history, file_info, *_sbn_run

            # ── Stream summary from LLM ───────────────────────────────────
            import datetime
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            metadata_block = (
                f"[Session metadata — use these exact values if asked:\n"
                f"  Model       : {model}\n"
                f"  Temperature : {temperature}\n"
                f"  Generated   : {now_str}]\n"
            )
            full_prompt = f"{metadata_block}\n{prompt.strip()}\n\n---\n\n{text}"

            try:
                llm = ChatOllama(model=model, base_url=ollama_base, temperature=temperature)
                response = ""
                for chunk in llm.stream(full_prompt):
                    token = chunk.content if hasattr(chunk, "content") else str(chunk)
                    response += token
                    history[-1]["content"] = response
                    yield history, file_info, *_sbn_run
            except Exception as exc:
                history[-1]["content"] = f"⚠ Error communicating with Ollama: {exc}"
            yield history, file_info, *_sbn_idle

        _sum_inputs  = [sum_file_input, sum_prompt, sum_model_dd,
                        sum_temperature_sl, ollama_url, sum_chatbot]
        _sum_outputs = [sum_chatbot, sum_file_info, sum_btn, sum_stop_btn]

        sum_run = sum_btn.click(summarize, inputs=_sum_inputs, outputs=_sum_outputs)
        sum_stop_btn.click(fn=None, cancels=[sum_run])

        sum_clear.click(
            lambda: ([], ""),
            outputs=[sum_chatbot, sum_file_info],
        )

        # ================================================================
        # Tab 6 — Automatic Updates
        # ================================================================
        with gr.Tab("⏰ Automatic Updates"):

            gr.Markdown(
                "## ⏰ Automatic Updates\n"
                "Schedule recurring **CourtListener searches** (to pull new opinions "
                "into a knowledge base) or **KB re-indexing** jobs "
                "(to pick up files added or changed outside the app).  "
                "Jobs run in the background while the app is open; "
                "the scheduler checks every minute."
            )

            with gr.Row():
                # ── Left: job list + controls ────────────────────────────
                with gr.Column(scale=3):
                    gr.Markdown("### 📋 Scheduled Jobs")
                    sched_table = gr.Dataframe(
                        headers=["ID", "Name", "Type", "KB", "Schedule",
                                 "Last Run", "Next Run", "Status", "Enabled"],
                        value=[],
                        interactive=False,
                        wrap=True,
                        label="",
                    )
                    sched_refresh_btn = gr.Button("↺ Refresh", size="sm",
                                                  variant="secondary")

                    gr.Markdown("### ▶ Job Actions")
                    with gr.Row():
                        sched_job_dd = gr.Dropdown(
                            choices=[],
                            label="Select job",
                            allow_custom_value=False,
                            scale=3,
                        )
                    with gr.Row():
                        sched_run_btn      = gr.Button("▶ Run Now",
                                                       variant="primary",   scale=1)
                        sched_enable_btn   = gr.Button("✓ Enable",
                                                       variant="secondary", scale=1)
                        sched_disable_btn  = gr.Button("✗ Disable",
                                                       variant="secondary", scale=1)
                        sched_delete_btn   = gr.Button("🗑 Delete",
                                                       variant="stop",      scale=1)
                    sched_action_status = gr.Markdown("")

                    gr.Markdown("### 📄 Job Log  (last 60 lines)")
                    sched_log_box = gr.Textbox(
                        label="",
                        lines=12,
                        interactive=False,
                        elem_classes=["log-box"],
                    )
                    sched_view_log_btn = gr.Button(
                        "↺ Refresh Log", size="sm", variant="secondary"
                    )

                # ── Right: add job form ──────────────────────────────────
                with gr.Column(scale=2):
                    gr.Markdown("### ➕ Add New Job")

                    sched_name = gr.Textbox(
                        label="Job Name",
                        placeholder="e.g.  Daily txca15 opinions",
                    )
                    sched_type = gr.Dropdown(
                        choices=[
                            ("Re-index Knowledge Base", "reindex_kb"),
                            ("CourtListener Search + Ingest", "cl_fetch_ingest"),
                        ],
                        label="Job Type",
                        value="reindex_kb",
                    )

                    # ── Re-index KB fields ───────────────────────────────
                    with gr.Group() as grp_reindex:
                        gr.Markdown("#### KB Settings")
                        sched_kb_dd = gr.Dropdown(
                            choices=list(load_registry().keys()),
                            label="Knowledge Base to re-index",
                            allow_custom_value=False,
                        )
                        sched_force_full = gr.Checkbox(
                            label="Force full re-index",
                            value=False,
                            info="Uncheck = incremental (recommended for daily runs).",
                        )

                    # ── CourtListener fetch fields ───────────────────────
                    with gr.Group(visible=False) as grp_cl:
                        gr.Markdown("#### CourtListener Search Parameters")
                        sched_cl_query = gr.Textbox(
                            label="Search Query",
                            placeholder="Leave blank to browse by court / date only",
                        )
                        with gr.Row():
                            sched_cl_court = gr.Textbox(
                                label="Court filter",
                                placeholder="txca15  scotus  ca9 …",
                                scale=2,
                            )
                            sched_cl_lookback = gr.Slider(
                                minimum=1, maximum=90, value=7, step=1,
                                label="Lookback (days)",
                                info="Fetch opinions issued in the last N days",
                                scale=2,
                            )
                        with gr.Row():
                            sched_cl_size = gr.Slider(
                                minimum=5, maximum=200, value=50, step=5,
                                label="Max results per run",
                                scale=2,
                            )
                            sched_cl_semantic = gr.Checkbox(
                                label="Semantic search",
                                value=False,
                                info="Uncheck for exact keyword matching",
                                scale=1,
                            )
                        gr.Markdown("#### Destination Knowledge Base")
                        sched_cl_kb_dd = gr.Dropdown(
                            choices=list(load_registry().keys()),
                            label="Add downloaded opinions to this KB",
                            allow_custom_value=False,
                        )

                    # ── Schedule definition ──────────────────────────────
                    gr.Markdown("#### Schedule")
                    sched_freq = gr.Dropdown(
                        choices=[
                            ("Every N hours",  "interval"),
                            ("Daily at …",     "daily"),
                            ("Weekly on …",    "weekly"),
                        ],
                        label="Frequency",
                        value="daily",
                    )
                    with gr.Row(visible=False) as row_interval:
                        sched_hours = gr.Slider(
                            minimum=1, maximum=168, value=24, step=1,
                            label="Interval (hours)",
                        )
                    with gr.Row(visible=True) as row_time:
                        sched_hour = gr.Dropdown(
                            choices=[f"{h:02d}" for h in range(24)],
                            value="02",
                            label="Hour  (24-hr)",
                            scale=1,
                        )
                        sched_minute = gr.Dropdown(
                            choices=["00", "15", "30", "45"],
                            value="00",
                            label="Minute",
                            scale=1,
                        )
                    with gr.Row(visible=False) as row_day:
                        sched_day = gr.Dropdown(
                            choices=["Monday", "Tuesday", "Wednesday",
                                     "Thursday", "Friday", "Saturday", "Sunday"],
                            value="Monday",
                            label="Day of week",
                        )

                    sched_add_btn    = gr.Button("➕ Add Job", variant="primary")
                    sched_add_status = gr.Markdown("")

        # ================================================================
        # Automatic Updates event handlers
        # ================================================================
        from rag.scheduler import (
            load_jobs, add_job, remove_job, set_job_enabled,
            run_job, next_run_str, DAYS_OF_WEEK,
        )

        def _jobs_to_table():
            jobs = load_jobs()
            reg  = load_registry()
            rows = []
            for j in jobs:
                sched  = j.get("schedule", {})
                stype  = sched.get("type", "daily")
                if stype == "interval":
                    sched_str = f"Every {sched.get('hours', 24)}h"
                elif stype == "daily":
                    sched_str = f"Daily {sched.get('hour','00')}:{sched.get('minute','00')}"
                else:
                    sched_str = (
                        f"Weekly {sched.get('day','Mon')} "
                        f"{sched.get('hour','00')}:{sched.get('minute','00')}"
                    )
                jtype_label = {
                    "reindex_kb":      "Re-index KB",
                    "cl_fetch_ingest": "CL Fetch+Ingest",
                }.get(j.get("type", ""), j.get("type", ""))
                rows.append([
                    j.get("id", ""),
                    j.get("name", ""),
                    jtype_label,
                    j.get("kb_name", ""),
                    sched_str,
                    (j.get("last_run") or "—")[:16],
                    next_run_str(j),
                    j.get("last_status") or "—",
                    "✓" if j.get("enabled", True) else "✗",
                ])
            return rows

        def _job_choices():
            return [
                f"{j.get('id','')} — {j.get('name','')}"
                for j in load_jobs()
            ]

        def _refresh_sched():
            choices = _job_choices()
            return (
                _jobs_to_table(),
                gr.Dropdown(choices=choices),
                gr.Dropdown(choices=list(load_registry().keys())),   # sched_kb_dd
                gr.Dropdown(choices=list(load_registry().keys())),   # sched_cl_kb_dd
            )

        sched_refresh_btn.click(
            _refresh_sched,
            outputs=[sched_table, sched_job_dd, sched_kb_dd, sched_cl_kb_dd],
        )

        # Refresh the jobs table every 60 s (status/last-run updates from background jobs).
        # The scheduler log is manual-only — click View Scheduler Log to refresh.
        sched_timer = gr.Timer(value=60)
        sched_timer.tick(
            lambda: _jobs_to_table(),
            outputs=[sched_table],
        )

        # ── Show/hide form sections based on job type ────────────────────
        def _on_type_change(jtype):
            is_cl = jtype == "cl_fetch_ingest"
            return gr.update(visible=not is_cl), gr.update(visible=is_cl)

        sched_type.change(
            _on_type_change,
            inputs=[sched_type],
            outputs=[grp_reindex, grp_cl],
        )

        # ── Show/hide schedule rows based on frequency ───────────────────
        def _on_freq_change(freq):
            return (
                gr.update(visible=(freq == "interval")),
                gr.update(visible=(freq in ("daily", "weekly"))),
                gr.update(visible=(freq == "weekly")),
            )

        sched_freq.change(
            _on_freq_change,
            inputs=[sched_freq],
            outputs=[row_interval, row_time, row_day],
        )

        # ── Add job ──────────────────────────────────────────────────────
        def _add_job(name, jtype, kb_name, force_full,
                     cl_query, cl_court, cl_lookback, cl_size, cl_semantic, cl_kb,
                     freq, hours, hour, minute, day):
            name = name.strip()
            if not name:
                return "⚠ Job name is required.", *_refresh_sched()

            # Schedule dict
            schedule: dict = {"type": freq}
            if freq == "interval":
                schedule["hours"] = int(hours)
            else:
                schedule["hour"]   = hour
                schedule["minute"] = minute
                if freq == "weekly":
                    schedule["day"] = day

            if jtype == "reindex_kb":
                if not kb_name:
                    return "⚠ Select a KB to re-index.", *_refresh_sched()
                job = {
                    "name":       name,
                    "type":       "reindex_kb",
                    "kb_name":    kb_name,
                    "force_full": force_full,
                    "schedule":   schedule,
                }
            else:  # cl_fetch_ingest
                if not cl_kb:
                    return "⚠ Select a destination KB.", *_refresh_sched()
                job = {
                    "name":    name,
                    "type":    "cl_fetch_ingest",
                    "kb_name": cl_kb,
                    "cl_params": {
                        "query":        cl_query.strip(),
                        "court":        cl_court.strip(),
                        "semantic":     cl_semantic,
                        "page_size":    int(cl_size),
                        "lookback_days": int(cl_lookback),
                    },
                    "schedule": schedule,
                }

            add_job(job)
            tbl, dd, kb1, kb2 = _refresh_sched()
            freq_label = (
                f"every {int(hours)}h" if freq == "interval"
                else f"daily at {hour}:{minute}" if freq == "daily"
                else f"weekly {day} {hour}:{minute}"
            )
            return f"✓ Job '{name}' added ({freq_label}).", tbl, dd, kb1, kb2

        sched_add_btn.click(
            _add_job,
            inputs=[
                sched_name, sched_type, sched_kb_dd, sched_force_full,
                sched_cl_query, sched_cl_court, sched_cl_lookback,
                sched_cl_size, sched_cl_semantic, sched_cl_kb_dd,
                sched_freq, sched_hours, sched_hour, sched_minute, sched_day,
            ],
            outputs=[sched_add_status, sched_table, sched_job_dd,
                     sched_kb_dd, sched_cl_kb_dd],
        )

        # ── Job actions ──────────────────────────────────────────────────
        def _parse_job_id(choice: str) -> str:
            return (choice or "").split(" — ")[0].strip()

        def _run_now(choice):
            job_id = _parse_job_id(choice)
            if not job_id:
                return "⚠ Select a job first.", _jobs_to_table()
            jobs = load_jobs()
            job  = next((j for j in jobs if j.get("id") == job_id), None)
            if not job:
                return "⚠ Job not found.", _jobs_to_table()
            import threading as _t
            import datetime as _dt
            result_box = []

            def _run():
                ran_at = _dt.datetime.now().isoformat(timespec="seconds")
                status = run_job(job)
                from rag.scheduler import _update_status
                _update_status(job_id, status, ran_at)

            _t.Thread(target=_run, daemon=True).start()
            return (
                f"▶ Job '{job.get('name','')}' started in background — "
                f"check the log for progress.",
                _jobs_to_table(),
            )

        def _enable_job(choice):
            job_id = _parse_job_id(choice)
            if not job_id:
                return "⚠ Select a job first.", _jobs_to_table()
            set_job_enabled(job_id, True)
            return "✓ Job enabled.", _jobs_to_table()

        def _disable_job(choice):
            job_id = _parse_job_id(choice)
            if not job_id:
                return "⚠ Select a job first.", _jobs_to_table()
            set_job_enabled(job_id, False)
            return "✓ Job disabled.", _jobs_to_table()

        def _delete_job(choice):
            job_id = _parse_job_id(choice)
            if not job_id:
                return "⚠ Select a job first.", _jobs_to_table()
            jobs = load_jobs()
            name = next((j.get("name","") for j in jobs if j.get("id") == job_id), job_id)
            remove_job(job_id)
            choices = _job_choices()
            return (
                f"✓ Job '{name}' deleted.",
                _jobs_to_table(),
                gr.Dropdown(choices=choices, value=None),
            )

        sched_run_btn.click(
            _run_now,
            inputs=[sched_job_dd],
            outputs=[sched_action_status, sched_table],
        )
        sched_enable_btn.click(
            _enable_job,
            inputs=[sched_job_dd],
            outputs=[sched_action_status, sched_table],
        )
        sched_disable_btn.click(
            _disable_job,
            inputs=[sched_job_dd],
            outputs=[sched_action_status, sched_table],
        )
        sched_delete_btn.click(
            _delete_job,
            inputs=[sched_job_dd],
            outputs=[sched_action_status, sched_table, sched_job_dd],
        )

        def _refresh_log():
            p = Path(__file__).parent / "data" / "scheduler.log"
            if not p.exists():
                return "(No log entries yet.)"
            lines = p.read_text(errors="replace").splitlines()
            return "\n".join(lines[-60:])

        sched_view_log_btn.click(_refresh_log, outputs=[sched_log_box])

    return demo


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LexLocal Legal AI")
    parser.add_argument("--host", default=None,
                        help="Bind address (default: 127.0.0.1; use --lan for 0.0.0.0)")
    parser.add_argument("--lan", action="store_true",
                        help="Bind to 0.0.0.0 so other devices on the LAN can connect")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--share", action="store_true", help="Create a public Gradio link")
    args = parser.parse_args()

    if args.host:
        host = args.host
    elif args.lan:
        host = "0.0.0.0"
        print(f"\n  LAN mode — open http://<this-machine-IP>:{args.port} on other devices\n")
    else:
        host = "127.0.0.1"

    # Start the background scheduler before launching the UI
    from rag.scheduler import start as _start_scheduler
    _start_scheduler()

    demo = build_ui(lan_mode=args.lan)
    demo.launch(
        server_name=host,
        server_port=args.port,
        share=args.share,
        show_error=True,
        theme=gr.themes.Soft(primary_hue="slate", neutral_hue="gray"),
        css="""
            .log-box textarea { font-family: monospace; font-size: 12px; }
            footer { display: none !important; }
        """,
    )

    # Make the live demo object available to URL-display handlers after launch.
    import app as _self
    _self._demo_ref = demo
