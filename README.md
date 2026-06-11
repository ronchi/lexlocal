# ⚖️ LexLocal

**A private, AI-powered legal research and document drafting assistant for solo attorneys, small firms, and pro-bono practitioners.**

LexLocal runs entirely on your own computer or office server. Your clients' confidential documents are never uploaded to the internet, never stored on a third-party server, and never processed by a commercial AI cloud service. Everything — the AI models, the document index, the search engine — runs locally on your own hardware.

---

## Who Is This For?

This application is built for:

- **Solo and small-firm attorneys** who need research and drafting assistance without the cost of large AI subscriptions or the compliance risk of uploading client files to third-party services.
- **Pro-bono practitioners** who work with limited resources and need to deliver high-quality legal work efficiently.
- **Legal aid organizations** looking for a self-hosted, privacy-preserving alternative to commercial legal AI tools.

---

## What It Does

LexLocal gives attorneys a private research assistant that can:

| Capability | Description |
|---|---|
| **Understand your documents** | Reads PDFs, Word files, Excel spreadsheets, and plain text, including scanned documents via OCR. Builds a searchable knowledge base that can be queried in plain English. |
| **Answer legal questions** | Finds the most relevant passages across all your loaded documents and reasons over them to answer questions, identify issues, or compare provisions — grounded in what you actually uploaded. |
| **Draft legal documents** | Generates motions, letters, memos, contract clauses, demand letters, interrogatories, and other documents based on the facts it has read from your files. |
| **Research case law** | Searches CourtListener's database of millions of federal and state judicial opinions by topic, court, or date range — and imports selected cases directly into your knowledge base. |
| **Summarize documents** | Produces structured legal summaries of individual documents covering parties, key facts, legal issues, holdings, deadlines, and action items. |
| **Stay current automatically** | Scheduled jobs can re-index your document folders or pull fresh opinions from CourtListener on a daily, weekly, or interval basis — no manual intervention required. |

---

## Features

### 📚 Knowledge Bases
- Create named, searchable collections from any folder of documents.
- Supports PDF (native and scanned), `.docx`, `.xlsx`, `.odt`, `.txt`, and `.md`.
- Incremental re-indexing: only new or changed files are processed on subsequent runs.
- Rename knowledge bases without re-indexing — existing embeddings are preserved.
- Delete knowledge bases without affecting the original documents.

### 💬 Chat (RAG Agent)
- Conversational interface with full session memory — follow-up questions build naturally on prior context.
- Select one or multiple knowledge bases per session to blend research across matters.
- Streaming responses appear token-by-token; a **⏹ Stop** button cancels any in-progress response.
- Configurable model and temperature, saved independently from the Summarizer.
- Grounded responses: if the answer isn't in your documents, the application says so.

### 🏛 CourtListener Integration
- Search by natural-language description (AI extracts structured parameters) or fill in fields manually.
- Filter by court (federal circuits, district courts, state courts), opinion issue date range, and keyword.
- Browse by court or date with no keyword required.
- Results include case name, court, date, and excerpt. Select any subset for download.
- Downloaded opinions are ingested directly into a new or existing knowledge base.
- Displays the exact API query sent to CourtListener for transparency.
- Retrieves up to 1,000 opinions per search.

### 📝 Document Summarizer
- Summarizes any single document into a structured Markdown report.
- Default sections: Document Overview, Parties, Key Facts, Legal Issues, Arguments/Holdings, Dates & Deadlines, Relief/Outcome, Notable Provisions and Risks.
- Fully editable prompt — customize focus and output format.
- Separate model and temperature from the Chat tab.
- Summary output includes model name, temperature, and generation timestamp for auditability.

### ⏰ Automatic Updates
- Schedule recurring **KB re-index** jobs to pick up new documents added to a folder.
- Schedule recurring **CourtListener fetch + ingest** jobs to pull the latest opinions on a topic or from a court.
- Dynamic date windows for CourtListener jobs (e.g., "last 7 days") — the job stays accurate indefinitely without manual updates.
- Three schedule types: daily at a time, weekly on a day/time, or every N hours.
- Run any job immediately on demand.
- Persistent scheduler log at `data/scheduler.log`.

### ⚙️ Settings
- Configurable Ollama server URL and embedding model.
- Separate model and temperature selectors for Chat and Summarizer, both persisted across sessions.
- CourtListener API token storage.
- **LAN mode indicator**: clearly shows whether the application is accessible to the office network, with instructions for enabling it if not.

### 🌐 LAN / Shared Office Use
- Start with `--lan` to serve the full application to any device on the local network — no installation required on client machines.
- The Settings tab displays the shareable URL and confirms LAN mode is active.
- All traffic stays on your private network.

---

## Technology Stack

| Component | Role |
|---|---|
| [Ollama](https://ollama.com) | Local LLM inference — runs AI models entirely on your hardware |
| [LlamaIndex](https://www.llamaindex.ai) | RAG pipeline, document chunking, and retrieval |
| [LanceDB](https://lancedb.com) | Embedded vector database (no separate server required) |
| [LangChain / LangGraph](https://langchain.com) | Agent orchestration and tool use |
| [Gradio](https://gradio.app) | Web UI |
| [PyMuPDF](https://pymupdf.readthedocs.io) | Fast native-text PDF extraction |
| [Docling](https://github.com/DS4SD/docling) + [EasyOCR](https://github.com/JaidedAI/EasyOCR) | OCR fallback for scanned documents |
| [CourtListener API](https://www.courtlistener.com/api/) | Judicial opinion search and download |

---

## Requirements

- **Python 3.11 or higher**
- **[Ollama](https://ollama.com/download)** installed and running
- Two Ollama models pulled (see Quick Start below):
  - `nomic-embed-text` — for document embedding
  - `gpt-oss:latest` — for chat and summarization (or any other supported model)
- **Hardware**: 16 GB RAM minimum; 32 GB recommended. Apple Silicon (M1/M2/M3) or an NVIDIA GPU significantly improves response times. The `llama3.3:70b` model requires approximately 43 GB of disk space.

---

## Quick Start

### 0. For Linux Mint users (and maybe others)

Check to ensure that Python's Tkinter module is installed

```bash
sudo apt install python3-tk
```

### 1. Install Ollama and pull the required models

Download Ollama from [https://ollama.com/download](https://ollama.com/download), install it, then run:

```bash
ollama pull nomic-embed-text
ollama pull gpt-oss:latest
```

> **Tip:** If disk space is limited, `mistral` (4.1 GB) or `llama3.2:3b` (2 GB) can be substituted for `llama3.3:70b`. They are less capable for complex legal work but run on modest hardware.

---

### 2. Clone the repository

```bash
git clone https://github.com/your-org/lexlocal.git
cd lexlocal
```

---

### 3. Create and activate a Python virtual environment

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

> **Windows note:** If you see an error about script execution being disabled, run this first:
> `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser`

---

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

This step takes 5–15 minutes the first time.

> **Linux note:** If EasyOCR fails to install due to CUDA errors, install the CPU-only version of PyTorch first:
> ```bash
> pip install torch --index-url https://download.pytorch.org/whl/cpu
> pip install -r requirements.txt
> ```

---

### 5. Run the application

**For personal use (this machine only):**
```bash
python app.py
```

**To share with colleagues on the same office network:**
```bash
python app.py --lan
```

Then open your browser and go to: **http://localhost:7860**

> When running with `--lan`, share your machine's IP address with colleagues. They open `http://<your-ip>:7860` in any browser — no installation required on their end.

---

### 6. First-time setup in the browser

1. Click the **⚙️ Settings** tab and click **Test Connection** to confirm Ollama is reachable.
2. Click the **📚 Knowledge Bases** tab.
3. Enter a name and the path to a folder of documents, then click **Add + Ingest Now**.
4. Once indexing is complete, click the **💬 Chat** tab, check your new knowledge base, and start asking questions.

---

## Optional: CourtListener API Token

A free CourtListener API token significantly raises the number of search results you can retrieve per hour. Register at [https://www.courtlistener.com/register/](https://www.courtlistener.com/register/), then enter your token in the **⚙️ Settings** tab.

---

## Optional: Run as a Service (Auto-Start on Boot)

For a shared office server you want running continuously, configure your OS to manage the application as a service:

**Linux (systemd):**
```ini
# /etc/systemd/system/lexlocal.service
[Unit]
Description=LexLocal Legal AI
After=network.target ollama.service
Wants=ollama.service

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/lexlocal
ExecStart=/path/to/lexlocal/.venv/bin/python app.py --lan --port 7860
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable lexlocal
sudo systemctl start lexlocal
```

**macOS (launchd):** See the full Installation Guide in `docs/LexLocal_Installation_Guide.docx`.

**Windows (Task Scheduler):** See the full Installation Guide in `docs/LexLocal_Installation_Guide.docx`.

---

## Documentation

Full documentation is in the `docs/` folder:

| Document | Contents |
|---|---|
| `LexLocal_Installation_Guide.docx` | Step-by-step installation for Windows 11, macOS, and Linux; LAN mode setup; auto-restart configuration; troubleshooting. |
| `LexLocal_User_Guide.docx` | Complete guide to all six application tabs; prompting techniques; CourtListener search; scheduling; tips for legal workflows; glossary. |

---

## Supported Document Types

| Format | Extension |
|---|---|
| PDF (native or scanned) | `.pdf` |
| Microsoft Word | `.docx` |
| Microsoft Excel | `.xlsx` |
| OpenDocument Text | `.odt` |
| Plain Text | `.txt` |
| Markdown | `.md` |

---

## Privacy and Data Handling

- **No data leaves your machine.** All AI inference runs through Ollama on your local hardware.
- **No cloud accounts required.** The only optional external service is the CourtListener API, which is a public legal database — no client document content is sent to it.
- **No telemetry.** The application does not call home or collect usage data.
- Documents, embeddings, settings, and knowledge bases are stored in the `data/` directory within the application folder.

---

## License

This project is licensed under the **MIT License** — see `LICENSE` for details.

> **Note:** [PyMuPDF](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright) is licensed under AGPL-3.0. For internal use within an organization (all users on the same private network), this is generally compatible with typical legal practice deployments. Organizations with specific compliance requirements may wish to obtain a PyMuPDF commercial license or substitute an alternative PDF library.

---

## Contributing

Pull requests are welcome. For significant changes, please open an issue first to discuss what you would like to change.

---

*Built for the attorneys who do the hardest work for the people who need it most.*
