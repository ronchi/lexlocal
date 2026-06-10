const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, VerticalAlign, PageNumber, PageBreak, ExternalHyperlink,
  TableOfContents, LevelFormat, UnderlineType
} = require("docx");
const fs = require("fs");

// ── Palette ──────────────────────────────────────────────────────────────────
const NAVY   = "1F3864";   // dark navy  – headings
const BLUE   = "2E5FA3";   // mid blue   – subheadings / rules
const LBLUE  = "D6E4F7";   // light blue – shaded callouts
const GOLD   = "C8A84B";   // gold       – warning callouts
const LGOLD  = "FFF8E7";   // light gold – warning background
const LGREEN = "E8F5E9";   // light green – tip background
const GREEN  = "2E7D32";   // green      – tip accent
const WHITE  = "FFFFFF";
const BLACK  = "000000";
const GRAY   = "F5F5F5";   // alternating table rows
const DGRAY  = "555555";   // body text (slightly softer than black)

// ── Helpers ──────────────────────────────────────────────────────────────────
const cm = n => Math.round(n * 567);   // centimetres → DXA  (1cm = 567 DXA)
const inch = n => Math.round(n * 1440);

const PAGE_W  = inch(8.5);
const PAGE_H  = inch(11);
const MARGIN  = inch(1);
const CONTENT_W = PAGE_W - MARGIN * 2;   // 9360

const cellBorder = (color = "CCCCCC") => ({
  top:    { style: BorderStyle.SINGLE, size: 1, color },
  bottom: { style: BorderStyle.SINGLE, size: 1, color },
  left:   { style: BorderStyle.SINGLE, size: 1, color },
  right:  { style: BorderStyle.SINGLE, size: 1, color },
});
const noBorder = () => ({
  top:    { style: BorderStyle.NONE, size: 0, color: WHITE },
  bottom: { style: BorderStyle.NONE, size: 0, color: WHITE },
  left:   { style: BorderStyle.NONE, size: 0, color: WHITE },
  right:  { style: BorderStyle.NONE, size: 0, color: WHITE },
});

// ── Typography helpers ────────────────────────────────────────────────────────
const body = (text, opts = {}) =>
  new Paragraph({
    spacing: { after: 160, line: 276 },
    children: [new TextRun({ text, font: "Calibri", size: 22, color: DGRAY, ...opts })],
  });

const bodyBold = (text) =>
  new Paragraph({
    spacing: { after: 160, line: 276 },
    children: [new TextRun({ text, font: "Calibri", size: 22, color: DGRAY, bold: true })],
  });

const bodyRuns = (runs, spacing = 160) =>
  new Paragraph({
    spacing: { after: spacing, line: 276 },
    children: runs.map(r =>
      typeof r === "string"
        ? new TextRun({ text: r, font: "Calibri", size: 22, color: DGRAY })
        : new TextRun({ font: "Calibri", size: 22, color: DGRAY, ...r })
    ),
  });

const spacer = (pt = 120) =>
  new Paragraph({ spacing: { after: pt }, children: [new TextRun("")] });

const rule = (color = BLUE) =>
  new Paragraph({
    spacing: { after: 160 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 4, color, space: 4 } },
    children: [new TextRun("")],
  });

const bullet = (text, level = 0) =>
  new Paragraph({
    numbering: { reference: "bullets", level },
    spacing: { after: 120, line: 276 },
    children: [new TextRun({ text, font: "Calibri", size: 22, color: DGRAY })],
  });

const bulletRuns = (runs, level = 0) =>
  new Paragraph({
    numbering: { reference: "bullets", level },
    spacing: { after: 120, line: 276 },
    children: runs.map(r =>
      typeof r === "string"
        ? new TextRun({ text: r, font: "Calibri", size: 22, color: DGRAY })
        : new TextRun({ font: "Calibri", size: 22, color: DGRAY, ...r })
    ),
  });

const numbered = (text, level = 0) =>
  new Paragraph({
    numbering: { reference: "steps", level },
    spacing: { after: 140, line: 276 },
    children: [new TextRun({ text, font: "Calibri", size: 22, color: DGRAY })],
  });

const numberedRuns = (runs, level = 0) =>
  new Paragraph({
    numbering: { reference: "steps", level },
    spacing: { after: 140, line: 276 },
    children: runs.map(r =>
      typeof r === "string"
        ? new TextRun({ text: r, font: "Calibri", size: 22, color: DGRAY })
        : new TextRun({ font: "Calibri", size: 22, color: DGRAY, ...r })
    ),
  });

// ── Callout boxes (implemented as single-cell tables) ─────────────────────────
const callout = (label, labelColor, bgColor, borderColor, paragraphs) => {
  const headerPara = new Paragraph({
    spacing: { after: 80 },
    children: [
      new TextRun({ text: label, font: "Calibri", size: 22, bold: true, color: labelColor }),
    ],
  });
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [CONTENT_W],
    rows: [
      new TableRow({
        children: [
          new TableCell({
            borders: {
              top:    { style: BorderStyle.SINGLE, size: 6, color: borderColor },
              bottom: { style: BorderStyle.SINGLE, size: 1, color: borderColor },
              left:   { style: BorderStyle.SINGLE, size: 1, color: borderColor },
              right:  { style: BorderStyle.SINGLE, size: 1, color: borderColor },
            },
            shading: { fill: bgColor, type: ShadingType.CLEAR },
            margins: { top: 120, bottom: 120, left: 180, right: 180 },
            width: { size: CONTENT_W, type: WidthType.DXA },
            children: [headerPara, ...paragraphs],
          }),
        ],
      }),
    ],
  });
};

const tipBox    = (...paras) => callout("💡  Tip",     GREEN,  LGREEN, GREEN,  paras);
const noteBox   = (...paras) => callout("ℹ️   Note",    BLUE,   LBLUE,  BLUE,   paras);
const warnBox   = (...paras) => callout("⚠️   Important", GOLD, LGOLD,  GOLD,   paras);

const calloutBody = (text) =>
  new Paragraph({
    spacing: { after: 80, line: 276 },
    children: [new TextRun({ text, font: "Calibri", size: 21, color: DGRAY })],
  });

const calloutBullet = (text) =>
  new Paragraph({
    numbering: { reference: "bullets", level: 0 },
    spacing: { after: 80, line: 276 },
    children: [new TextRun({ text, font: "Calibri", size: 21, color: DGRAY })],
  });

// ── Two-column layout helper ─────────────────────────────────────────────────
const twoCol = (leftParas, rightParas, leftW, rightW) => {
  const rw = rightW || (CONTENT_W - leftW - 360);
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [leftW, 360, rw],
    rows: [
      new TableRow({
        children: [
          new TableCell({ borders: noBorder(), width: { size: leftW, type: WidthType.DXA },
            children: leftParas }),
          new TableCell({ borders: noBorder(), width: { size: 360, type: WidthType.DXA },
            children: [spacer()] }),
          new TableCell({ borders: noBorder(), width: { size: rw, type: WidthType.DXA },
            children: rightParas }),
        ],
      }),
    ],
  });
};

// ── Two-column data table ─────────────────────────────────────────────────────
const dataTable = (headers, rows, colW) => {
  const totalW = colW.reduce((a, b) => a + b, 0);
  const makeCell = (text, isHeader = false, fill = WHITE) =>
    new TableCell({
      borders: cellBorder("BBBBBB"),
      shading: { fill, type: ShadingType.CLEAR },
      margins: { top: 80, bottom: 80, left: 120, right: 120 },
      width: { size: colW[0], type: WidthType.DXA },
      children: [new Paragraph({
        spacing: { after: 0 },
        children: [new TextRun({
          text, font: "Calibri", size: 20,
          bold: isHeader, color: isHeader ? WHITE : DGRAY,
        })],
      })],
    });

  const headerRow = new TableRow({
    tableHeader: true,
    children: headers.map((h, i) =>
      new TableCell({
        borders: cellBorder(NAVY),
        shading: { fill: NAVY, type: ShadingType.CLEAR },
        margins: { top: 100, bottom: 100, left: 120, right: 120 },
        width: { size: colW[i], type: WidthType.DXA },
        children: [new Paragraph({
          spacing: { after: 0 },
          children: [new TextRun({ text: h, font: "Calibri", size: 20, bold: true, color: WHITE })],
        })],
      })
    ),
  });

  const dataRows = rows.map((row, ri) =>
    new TableRow({
      children: row.map((cell, ci) =>
        new TableCell({
          borders: cellBorder("BBBBBB"),
          shading: { fill: ri % 2 === 0 ? WHITE : GRAY, type: ShadingType.CLEAR },
          margins: { top: 80, bottom: 80, left: 120, right: 120 },
          width: { size: colW[ci], type: WidthType.DXA },
          children: [new Paragraph({
            spacing: { after: 0 },
            children: typeof cell === "string"
              ? [new TextRun({ text: cell, font: "Calibri", size: 20, color: DGRAY })]
              : cell,
          })],
        })
      ),
    })
  );

  return new Table({
    width: { size: totalW, type: WidthType.DXA },
    columnWidths: colW,
    rows: [headerRow, ...dataRows],
  });
};

// ── Heading helpers (no color on built-in headings — use custom paragraphs) ──
const h1 = (text) =>
  new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 360, after: 160 },
    children: [new TextRun({ text, font: "Calibri", size: 36, bold: true, color: NAVY })],
  });

const h2 = (text) =>
  new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 280, after: 120 },
    children: [new TextRun({ text, font: "Calibri", size: 28, bold: true, color: BLUE })],
  });

const h3 = (text) =>
  new Paragraph({
    heading: HeadingLevel.HEADING_3,
    spacing: { before: 200, after: 100 },
    children: [new TextRun({ text, font: "Calibri", size: 24, bold: true, color: NAVY })],
  });

// ── Cover page ────────────────────────────────────────────────────────────────
const coverPage = [
  spacer(inch(0.8)),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 0 },
    children: [new TextRun({ text: "ACCESS TO JUSTICE", font: "Calibri", size: 64, bold: true, color: NAVY })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 80 },
    children: [new TextRun({ text: "AI-Powered Legal Document Assistant", font: "Calibri", size: 32, color: BLUE, italics: true })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 600 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: GOLD, space: 8 } },
    children: [new TextRun("")],
  }),
  spacer(400),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 120 },
    children: [new TextRun({ text: "User Guide", font: "Calibri", size: 40, bold: true, color: DGRAY })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 80 },
    children: [new TextRun({ text: "For Attorneys and Legal Professionals", font: "Calibri", size: 26, color: DGRAY })],
  }),
  spacer(600),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 60 },
    children: [new TextRun({ text: "Version 1.0   •   June 2026", font: "Calibri", size: 22, color: "888888" })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 60 },
    children: [new TextRun({ text: "Runs entirely on your own computer — your documents never leave your network",
      font: "Calibri", size: 22, color: "888888", italics: true })],
  }),
  new Paragraph({ children: [new PageBreak()] }),
];

// ── Table of Contents page ────────────────────────────────────────────────────
const tocPage = [
  h1("Table of Contents"),
  new TableOfContents("Table of Contents", {
    hyperlink: true,
    headingStyleRange: "1-3",
    stylesWithLevels: [
      { styleName: "Heading1", level: 1 },
      { styleName: "Heading2", level: 2 },
      { styleName: "Heading3", level: 3 },
    ],
  }),
  new Paragraph({ children: [new PageBreak()] }),
];

// ── Section 1 — Introduction ──────────────────────────────────────────────────
const section1 = [
  h1("1.  Introduction"),
  rule(),
  body("Access to Justice is a private, AI-powered research and drafting assistant that runs entirely on your own computer. It reads the documents you give it — contracts, pleadings, correspondence, depositions, statutes, and more — and lets you ask questions or request drafts in plain English, just as you would with a knowledgeable colleague."),
  spacer(80),
  body("Because everything runs locally, your clients’ confidential documents are never uploaded to the internet, never stored on a third-party server, and never shared with any AI company."),
  spacer(120),

  h2("1.1  What the Application Does"),
  body("At its core, the application does three things:"),
  bullet("Reads your documents (PDFs, Word files, spreadsheets) and builds a searchable knowledge base from them."),
  bullet("Answers your questions by finding the most relevant passages in those documents and reasoning over them."),
  bullet("Drafts legal documents — motions, letters, memos, contract clauses — grounded in the facts it has read."),
  spacer(120),

  h2("1.2  What You Do Not Need to Know"),
  body("You do not need to know anything about artificial intelligence, programming, or databases to use this application. This guide explains every feature in plain language. The only computer skills you need are:"),
  bullet("Opening a web browser (the application looks and feels like a website)."),
  bullet("Knowing where your document folders are stored on your computer."),
  bullet("Typing questions as you would type an email."),
  spacer(120),

  noteBox(
    calloutBody("This application requires a separate program called Ollama to be running in the background. Ollama provides the AI model that reads and reasons over your documents. Your IT contact will have set this up for you. You do not need to interact with Ollama directly.")
  ),
  spacer(120),
  new Paragraph({ children: [new PageBreak()] }),
];

// ── Section 2 — Starting the Application ─────────────────────────────────────
const section2 = [
  h1("2.  Starting the Application"),
  rule(),
  body("The application is started from a Terminal window by your IT support. Once it is running, you open it in any web browser on your computer — or on any computer connected to the same office network if your IT contact has configured it for network use."),
  spacer(120),

  h2("2.1  Opening the Application in Your Browser"),
  numbered("Open any web browser (Safari, Chrome, Edge, or Firefox)."),
  numberedRuns([
    "In the address bar at the top, type exactly: ",
    { text: "http://localhost:7860", bold: true },
    " and press Enter."
  ]),
  numbered("The Access to Justice application will load. You will see two tabs at the top: “Settings & Knowledge Bases” and “Chat.”"),
  spacer(120),

  tipBox(
    calloutBody("If you are opening the application from a different computer on your office network, your IT contact will give you a different address to type — something like http://192.168.1.50:7860. Use that address instead of localhost.")
  ),
  spacer(120),

  h2("2.2  What You Will See"),
  body("The application has two main areas, accessible through tabs near the top of the page:"),
  spacer(80),
  dataTable(
    ["Tab", "What it is for"],
    [
      ["⚙️  Settings & Knowledge Bases", "Set up and manage your document collections. This is also where you configure the AI model and view application URLs for sharing with colleagues."],
      ["💬  Chat", "Ask questions, request research, and generate drafts based on the documents you have loaded."],
    ],
    [3200, 6160]
  ),
  spacer(200),
  new Paragraph({ children: [new PageBreak()] }),
];

// ── Section 3 — Knowledge Bases ───────────────────────────────────────────────
const section3 = [
  h1("3.  Setting Up Knowledge Bases"),
  rule(),

  h2("3.1  What is a Knowledge Base?"),
  body("A Knowledge Base (often shortened to “KB” in the interface) is a searchable collection built from the documents in a single folder on your computer. Think of it like a binder: you put related documents into a folder, give the folder a meaningful name, and the application reads every document in that folder and indexes it so it can be searched instantly."),
  spacer(100),
  body("Examples of how attorneys typically organize Knowledge Bases:"),
  bullet("One KB per client matter  (e.g., “Smith v. Jones — 2024”)"),
  bullet("One KB per document type  (e.g., “Contract Templates”, “Depositions”)"),
  bullet("One KB for reference materials  (e.g., “Texas Family Code”, “Federal Rules of Civil Procedure”)"),
  spacer(100),

  tipBox(
    calloutBody("You can select multiple Knowledge Bases at once in the Chat tab. This lets you ask questions that span several matters or combine case documents with reference materials in a single conversation.")
  ),
  spacer(120),

  h2("3.2  Supported Document Types"),
  body("The application can read the following types of documents:"),
  spacer(80),
  dataTable(
    ["File Type", "Extension", "Notes"],
    [
      ["PDF",                    ".pdf",  "Both native (computer-generated) and scanned paper documents. Scanned documents take longer to process."],
      ["Word Document",          ".docx", "Microsoft Word files."],
      ["Excel Spreadsheet",      ".xlsx", "Microsoft Excel files. Each sheet is read separately."],
      ["OpenDocument Text",      ".odt",  "LibreOffice / OpenOffice Writer files."],
      ["Plain Text",             ".txt",  "Simple text files."],
      ["Markdown",               ".md",   "Formatted plain-text files."],
    ],
    [2400, 1200, 5760]
  ),
  spacer(200),

  warnBox(
    calloutBody("Scanned PDF documents (paper documents that were photocopied or faxed and then saved as PDFs) take significantly longer to process than documents created directly on a computer. A folder of 300 scanned PDFs may take 20–30 minutes to index. This is normal. The application will display a progress bar while it works.")
  ),
  spacer(120),

  h2("3.3  Creating a New Knowledge Base"),
  body("Before you can chat with your documents, you must create at least one Knowledge Base. Follow these steps:"),
  spacer(80),

  h3("Step 1 — Navigate to the Settings tab"),
  body("Click the “⚙️ Settings & Knowledge Bases” tab at the top of the page."),
  spacer(80),

  h3("Step 2 — Enter a name and folder path"),
  body("In the “Add Knowledge Base” section on the right side of the screen:"),
  numbered("In the “Knowledge Base Name” field, type a short, descriptive name. For example: Bankruptcy Matter — Hernandez or Contract Templates."),
  numberedRuns([
    "In the “Folder Path” field, type the full path to the folder on your computer that contains the documents. For example: ",
    { text: "/Users/yourname/Documents/Hernandez-Bankruptcy", font: "Courier New", size: 20 },
    "."
  ]),
  spacer(60),
  noteBox(
    calloutBody("To find the full path of a folder on a Mac: right-click the folder in Finder, hold the Option key, and choose “Copy “Foldername” as Pathname.” On Windows: hold Shift and right-click the folder, then choose “Copy as path.” Paste that value into the Folder Path field.")
  ),
  spacer(80),

  h3("Step 3 — Start the ingestion process"),
  numbered("Click the green “Add + Ingest Now” button. The application will immediately begin reading every document in the folder."),
  numbered("A log window will appear below the button showing real-time progress: which file is being processed, how many words were extracted, and a progress bar showing how far along the embedding step is."),
  numbered("When the process is complete you will see a message such as: ✓ Done! Indexed 47 document(s) into KB ‘Hernandez Bankruptcy’ in 340s (5.7 min)."),
  numbered("The Knowledge Bases table will automatically update to show the KB name, its status (“✓ Indexed”), and the number of documents."),
  spacer(120),

  tipBox(
    calloutBody("You can continue using the application — including asking questions on the Chat tab — while a Knowledge Base is being built in the background. The new KB will appear in the Chat tab’s selection list automatically once indexing is complete.")
  ),
  spacer(120),

  h2("3.4  Understanding the Ingestion Progress Log"),
  body("During indexing, a running log is displayed on screen. Here is what the key messages mean:"),
  spacer(80),
  dataTable(
    ["Log Message", "What It Means"],
    [
      ["Found 47 file(s) to ingest", "The application has counted the documents in your folder and is ready to begin."],
      ["[12/47 26%] filename.pdf", "It is currently processing the 12th document out of 47 (26% complete)."],
      ["✓ Native text layer found (PyMuPDF)", "This PDF has embedded text and was read instantly."],
      ["No native text layer — trying Docling", "This is a scanned document. The application is using optical character recognition (OCR) to read it. This takes longer."],
      ["Extracted 4,823 words in 2.3s", "Text extraction succeeded for this document."],
      ["⚠ No text extracted — skipping", "The application could not read any text from this file. It will be skipped. See Section 7 (Troubleshooting) for guidance."],
      ["Phase 3: Embedding 1,843 chunks", "All documents have been read. The application is now converting the text into a searchable mathematical format. This step has its own progress bar."],
      ["[████████░░] 800/1843 (43%)", "The embedding progress bar. The filled blocks show how much is done."],
      ["✓ Done! Indexed 47 document(s)", "The Knowledge Base is complete and ready to use."],
    ],
    [3400, 5960]
  ),
  spacer(200),

  h2("3.5  Managing Existing Knowledge Bases"),
  body("The “Modify a Knowledge Base” section allows you to re-index or delete any existing KB using a single dropdown menu."),
  spacer(80),

  h3("Re-indexing a Knowledge Base"),
  body("Re-indexing rebuilds a Knowledge Base from scratch. Do this when:"),
  bullet("You have added new documents to the folder."),
  bullet("You have deleted or replaced documents in the folder."),
  bullet("A previous indexing run produced errors on some files."),
  spacer(80),
  numbered("In the “Select Knowledge Base” dropdown, choose the KB you want to re-index."),
  numbered("Click the blue “↺ Re-index” button."),
  numbered("The progress log will appear and the process will run exactly as during initial creation."),
  spacer(120),

  h3("Deleting a Knowledge Base"),
  numbered("In the “Select Knowledge Base” dropdown, choose the KB you want to remove."),
  numbered("Click the red “🗑 Delete” button."),
  numbered("The KB will be removed from the list and its index will be deleted. The original documents in your folder are not affected."),
  spacer(80),
  warnBox(
    calloutBody("Deleting a Knowledge Base cannot be undone. If you need it again, you will need to re-ingest the folder. Your original documents are never deleted — only the index inside the application is removed.")
  ),
  spacer(120),
  new Paragraph({ children: [new PageBreak()] }),
];

// ── Section 4 — Using the Chat Interface ──────────────────────────────────────
const section4 = [
  h1("4.  Using the Chat Interface"),
  rule(),
  body("The Chat tab is where you conduct research, ask questions, and request drafts. It works much like a text message conversation or an email thread: you type a question, the application responds, and you can continue the conversation with follow-up questions."),
  spacer(120),

  h2("4.1  Setting Up a Chat Session"),
  body("Before you type your first question, take a moment to configure three items in the left panel of the Chat tab:"),
  spacer(80),

  h3("Choose Your Knowledge Bases"),
  body("Under “Active Knowledge Bases,” you will see checkboxes for every indexed KB. Check the ones you want the application to search when answering your questions."),
  bullet("You can select one KB or several at once."),
  bullet("If you select multiple KBs, the application will search all of them and blend the results."),
  bullet("Leave all boxes unchecked if you want a general legal question answered without reference to your specific documents."),
  spacer(100),
  tipBox(
    calloutBody("For a focused research question about a single matter, select only that matter’s KB. For a question that requires comparing documents across matters — such as identifying all contracts with a particular clause — select all relevant KBs.")
  ),
  spacer(120),

  h3("Choose an AI Model"),
  body("The “Chat Model” dropdown lists the AI models available on your computer. Different models have different strengths:"),
  spacer(80),
  dataTable(
    ["Model Name", "Best Used For"],
    [
      ["llama3.3:70b",  "General legal research, document analysis, and drafting. A strong all-around choice."],
      ["deepseek-r1",   "Complex multi-step legal reasoning problems. Slower, but thinks through problems more carefully."],
      ["mistral",       "Faster responses for straightforward questions. Good for quick lookups."],
      ["qwen2.5",       "Well-rounded model with strong reading comprehension across long documents."],
    ],
    [2400, 6960]
  ),
  spacer(120),
  noteBox(
    calloutBody("The models listed depend on which ones your IT contact has installed. If a model name does not appear in the dropdown, ask your IT contact to install it. Click “↺ Refresh Models” to update the list after a new model is installed.")
  ),
  spacer(120),

  h3("Adjust the Temperature"),
  body("The “Temperature” slider controls how creative or conservative the AI’s responses are. Think of it as a dial between “precise” and “creative.”"),
  spacer(80),
  dataTable(
    ["Temperature Setting", "Effect", "Best For"],
    [
      ["0.0 – 0.2  (Low)",    "Very consistent and literal. Stays closely to the documents.", "Summarizing facts, extracting specific terms, checking dates or figures."],
      ["0.3 – 0.6  (Medium)", "Balances accuracy with natural, readable prose.", "Most legal research and drafting tasks."],
      ["0.7 – 1.0  (High)",   "More varied and creative language.", "Brainstorming arguments, generating multiple drafting alternatives."],
    ],
    [2200, 3000, 4160]
  ),
  spacer(100),
  tipBox(
    calloutBody("For most legal work, a temperature between 0.1 and 0.3 is recommended. This keeps the application focused on what is actually in your documents rather than speculating.")
  ),
  spacer(120),

  h2("4.2  Writing Effective Prompts"),
  body("A “prompt” is simply what you type into the chat box. The quality of the answer depends heavily on the quality of the question. Here are principles that work well for legal tasks:"),
  spacer(80),

  h3("Be Specific"),
  body("Instead of asking a vague question, include the key facts, parties, or document names you care about."),
  spacer(60),
  dataTable(
    ["✖  Less Effective", "✔  More Effective"],
    [
      ["What does the contract say?", "What does the Master Services Agreement with Apex Corp say about limitation of liability and indemnification?"],
      ["Find any problems.", "Identify any clauses in the lease agreement that conflict with Texas Property Code § 92.056 regarding repair obligations."],
      ["Write a letter.", "Draft a demand letter to opposing counsel requesting the production of all financial statements from 2020 to 2024 referenced in the complaint."],
    ],
    [4320, 5040]
  ),
  spacer(120),

  h3("Ask Follow-Up Questions"),
  body("The application remembers the entire conversation within a session. You do not need to re-explain the matter with every question. For example:"),
  bullet("First prompt:  “Summarize the key obligations of each party under the Johnson franchise agreement.”"),
  bullet("Follow-up:  “Are there any provisions in that agreement that would allow early termination without penalty?”"),
  bullet("Follow-up:  “Draft a letter to the franchisor citing those provisions and requesting a meeting to discuss termination.”"),
  spacer(120),

  h3("Request Specific Document Types"),
  body("The application can draft a wide range of legal documents. Be explicit about what you need:"),
  bullet("“Draft a motion for summary judgment based on the depositions in this matter.”"),
  bullet("“Write a memorandum of law analyzing the breach of contract claims.”"),
  bullet("“Prepare a chronology of events from the emails in the discovery folder.”"),
  bullet("“Draft interrogatories focused on the damages claimed in the complaint.”"),
  spacer(120),

  h2("4.3  Understanding the Response"),
  body("While the application is working, you will see a series of status messages in the chat bubble:"),
  spacer(80),
  dataTable(
    ["Status Message", "What the Application is Doing"],
    [
      ["⌛ Thinking…",                            "The AI model received your question and is deciding how to answer it."],
      ["🔍 Searching knowledge bases…",    "The application is searching your selected document folders for relevant passages."],
      ["✓ Searching complete — reasoning…", "Relevant passages have been found. The AI is now reading them and composing an answer."],
      ["📝 Drafting document…",            "The application is generating a draft document as you requested."],
    ],
    [3600, 5760]
  ),
  spacer(100),
  body("Once the response begins appearing, it will stream word by word — much like watching someone type in real time. You do not need to wait for it to finish before you start reading."),
  spacer(120),

  h2("4.4  Interpreting and Verifying Responses"),
  warnBox(
    calloutBody("The application is a research and drafting tool, not a licensed attorney. Always review its responses critically before relying on them in legal proceedings. The application may occasionally cite a passage imprecisely or miss a nuance that requires professional judgment. Treat its output as you would a first draft from a junior associate: useful and time-saving, but requiring your review and sign-off.")
  ),
  spacer(120),
  body("Responses are formatted using Markdown, which means:"),
  bullet("Headings appear in bold larger text."),
  bullet("Key terms or citations may appear in bold."),
  bullet("Lists of items appear as numbered or bulleted lists."),
  bullet("Longer drafts will be divided into clearly labeled sections."),
  spacer(100),
  body("Each response is grounded in the documents you provided. If the application cannot find relevant information in your KBs, it will say so explicitly rather than inventing an answer."),
  spacer(120),

  h2("4.5  Clearing the Conversation"),
  body("Click the “Clear Conversation” button below the chat box to start a fresh session. This erases the current conversation history. Your Knowledge Bases and settings are not affected."),
  spacer(120),
  new Paragraph({ children: [new PageBreak()] }),
];

// ── Section 5 — Settings Panel ────────────────────────────────────────────────
const section5 = [
  h1("5.  Settings and Connection"),
  rule(),

  h2("5.1  Ollama Server Settings"),
  body("The “Ollama Server” panel on the left side of the Settings tab contains two fields:"),
  spacer(80),
  dataTable(
    ["Field", "What It Does"],
    [
      ["Ollama Base URL",  "The address of the AI server running on your computer. This is pre-filled with the correct value (http://localhost:11434) and should not be changed unless your IT contact instructs you to."],
      ["Embedding Model", "The model used to make your documents searchable. This is pre-filled with the recommended value (nomic-embed-text) and should not be changed."],
    ],
    [2800, 6560]
  ),
  spacer(100),
  body("Click “Test Connection” to verify that the AI server is running. You will see a message confirming the connection and listing the available models, or a warning if the server is not reachable."),
  spacer(120),

  h2("5.2  App URLs — Sharing the Application"),
  body("At the bottom of the Settings tab you will find the “App URLs” section. This shows the web addresses that other people can use to open the application in their browser."),
  spacer(80),
  dataTable(
    ["URL Field", "When to Use It"],
    [
      ["Local / LAN URL",       "Share this with colleagues on the same office network. They open this address in their browser to use the application from their own desk without installing anything."],
      ["Public Share URL",      "A temporary internet address valid for 72 hours. Only available when the application is started with the --share option. Use this to give access to someone outside your office network."],
    ],
    [2800, 6560]
  ),
  spacer(100),
  body("Click the copy icon (📋) next to either URL box to copy the address to your clipboard, then paste it into an email or message to send to a colleague."),
  spacer(100),
  noteBox(
    calloutBody("The URL fields are populated automatically within a few seconds of the page loading. If they appear empty, click the “↺ Refresh” button next to the URL boxes.")
  ),
  spacer(120),
  new Paragraph({ children: [new PageBreak()] }),
];

// ── Section 6 — Tips for Best Results ─────────────────────────────────────────
const section6 = [
  h1("6.  Tips for Best Results"),
  rule(),

  h2("6.1  Organizing Your Document Folders"),
  bullet("Keep each matter’s documents in its own folder. This makes it easy to create focused KBs and prevents the application from mixing up facts between matters."),
  bullet("Use clear, descriptive folder names. The folder name does not appear in responses, but a good Knowledge Base name (which you assign at ingestion time) helps you identify the right KB quickly."),
  bullet("Remove password protection from PDFs before ingesting them. The application cannot read encrypted documents."),
  bullet("If a document exists as both a Word file and a PDF, prefer the Word version. It will be read more accurately and much faster than a scanned PDF."),
  spacer(120),

  h2("6.2  Getting Better Answers"),
  bullet("Select only the KBs relevant to your current question. Selecting unrelated KBs adds noise and may dilute the quality of the answer."),
  bullet("For long documents such as contracts or statutes, ask targeted questions rather than “tell me everything about this document.”"),
  bullet("If an answer seems incomplete, ask the application to expand: “Please elaborate on the indemnification clause you mentioned.”"),
  bullet("If you need the application to cite its sources more precisely, ask explicitly: “Which document and page does that come from?”"),
  bullet("Use the low-temperature setting (0.1) when accuracy matters most, and a slightly higher setting (0.4–0.5) when you want the application to write in a more natural, flowing style."),
  spacer(120),

  h2("6.3  Multi-Step Legal Tasks"),
  body("The application is designed to handle multi-step tasks within a single conversation. For example:"),
  numbered("Ask for a factual summary:  “Summarize the facts alleged in the Hernandez complaint.”"),
  numbered("Build on it:  “Based on those facts, what causes of action appear strongest?”"),
  numbered("Request a draft:  “Draft the argument section of a motion to dismiss addressing the breach of contract count.”"),
  numbered("Refine:  “Rewrite the second paragraph to be more concise and omit references to the 2019 agreement.”"),
  spacer(100),
  body("Each step builds on the previous one without you needing to re-explain the matter. This mirrors how you might work through an issue with a research associate."),
  spacer(120),

  h2("6.4  Confidentiality Reminder"),
  tipBox(
    calloutBody("Because the application runs entirely on your machine (or your firm’s local server), no document content, no client name, and no query is ever sent to the internet — unless you specifically enable the public share URL. Your use of this application is private by design.")
  ),
  spacer(120),
  new Paragraph({ children: [new PageBreak()] }),
];

// ── Section 7 — Troubleshooting ───────────────────────────────────────────────
const section7 = [
  h1("7.  Troubleshooting"),
  rule(),
  body("This section covers the most common issues you may encounter and what to do about them. If a problem persists after following these steps, contact your IT support and share the contents of the ingestion log file (see Section 7.5)."),
  spacer(120),

  h2("7.1  The Application Will Not Open"),
  dataTable(
    ["Symptom", "Likely Cause", "What to Do"],
    [
      ["Browser shows “This site can’t be reached” or “Connection refused”", "The application is not running.", "Ask your IT contact to start the application. It must be launched from a Terminal window before you can open it in a browser."],
      ["Page loads but shows an error about the AI model", "Ollama is not running.", "Ask your IT contact to start Ollama. It runs as a background service and must be running before the application starts."],
      ["Application opens but the model dropdown is empty", "Ollama has no models installed.", "Click “Test Connection” to confirm Ollama is reachable, then ask your IT contact to install the required models."],
    ],
    [2400, 2760, 4200]
  ),
  spacer(120),

  h2("7.2  Ingestion Fails or Documents Are Skipped"),
  dataTable(
    ["Symptom", "Likely Cause", "What to Do"],
    [
      ["⚠ No text extracted — skipping", "The PDF is encrypted or completely unreadable.", "Remove password protection from the PDF, or try re-saving it from Word/Adobe as a non-encrypted file."],
      ["RapidOCR returned empty result", "The PDF is a very poor quality scan.", "Try scanning the original paper document again at a higher resolution (300 DPI or more), then re-ingest."],
      ["The progress log stops updating for a long time", "A very large or complex document is being processed.", "Wait. Scanned PDFs can take several minutes each. Check the terminal window for live progress, or tail the log file (see Section 7.5)."],
      ["Ingestion completes but the document count seems too low", "Some files may not be in a supported format.", "Check that all files use a supported extension (.pdf, .docx, .xlsx, .odt, .txt, .md). Files such as .doc (old Word format) or .pages (Apple Pages) are not supported."],
    ],
    [2800, 2560, 4000]
  ),
  spacer(120),

  h2("7.3  Chat Responses Are Poor or Off-Topic"),
  dataTable(
    ["Symptom", "Likely Cause", "What to Do"],
    [
      ["Answer does not reference the documents at all", "No KB is selected, or the selected KB has not been indexed.", "Check that at least one KB is checked in the Chat tab and that its status shows ✓ Indexed in the Settings tab."],
      ["Answer mixes up facts from different matters", "Multiple unrelated KBs are selected.", "Deselect KBs that are not relevant to the current question."],
      ["Answer is vague or generic", "The prompt is too broad.", "Rewrite the question to be more specific. Include party names, document names, or specific issues."],
      ["Application seems to freeze after sending a prompt", "A large response is being generated.", "Wait — the application is still working. You will see status messages (⌛ Thinking, 🔍 Searching…) while it processes. Complex questions on large document sets can take 1–3 minutes."],
    ],
    [2800, 2560, 4000]
  ),
  spacer(120),

  h2("7.4  Sharing and Network Access"),
  dataTable(
    ["Symptom", "Likely Cause", "What to Do"],
    [
      ["A colleague cannot reach the application over the network", "Application was not started in LAN mode.", "Ask your IT contact to restart the application with the --lan option."],
      ["The Public Share URL field shows “not enabled”", "The application was not started with --share.", "Ask your IT contact to restart with the --share option. Note that the public URL expires after 72 hours."],
      ["URL fields are empty after loading the page", "The page loaded before the URLs were ready.", "Click “↺ Refresh” next to the URL boxes, or wait a few seconds and the fields will populate automatically."],
    ],
    [2800, 2560, 4000]
  ),
  spacer(120),

  h2("7.5  Viewing the Ingestion Log"),
  body("A complete log of every ingestion run is saved automatically to a file on your computer. This log is invaluable for diagnosing problems, especially for large batches of documents."),
  spacer(80),
  body("To view the log within the application:"),
  numbered("Go to the “⚙️ Settings & Knowledge Bases” tab."),
  numbered("Scroll to the bottom of the page."),
  numbered("Click “📋 View Ingestion Log File.” The last 100 lines of the log will appear on screen."),
  spacer(100),
  body("To share the full log with your IT contact, the log file is located at:"),
  new Paragraph({
    spacing: { after: 160 },
    indent: { left: 720 },
    children: [new TextRun({ text: "[application folder]/data/ingestion.log", font: "Courier New", size: 20, color: NAVY })],
  }),
  spacer(120),
  new Paragraph({ children: [new PageBreak()] }),
];

// ── Section 8 — Glossary ──────────────────────────────────────────────────────
const section8 = [
  h1("8.  Glossary"),
  rule(),
  body("The following terms appear in this guide and in the application interface."),
  spacer(120),
  dataTable(
    ["Term", "Plain-Language Definition"],
    [
      ["AI Model",          "The artificial intelligence program that reads your documents and generates answers. Different models (such as Llama, Mistral, or DeepSeek) have different strengths, speeds, and sizes."],
      ["Chunk",             "A short passage — typically a few paragraphs — that the application cuts your documents into before indexing. Searching by chunk allows the application to find the most relevant portion of a long document quickly."],
      ["Embedding",         "A mathematical representation of a piece of text. The application converts every chunk of your documents into an embedding so it can measure how closely any two pieces of text are related in meaning, not just by keywords."],
      ["Ingestion",         "The process of reading, converting, and indexing the documents in a folder. Once a folder has been ingested, its contents become searchable."],
      ["Knowledge Base (KB)", "A named, searchable index built from all the documents in a specific folder. Each KB corresponds to one folder on your computer."],
      ["LAN",               "Local Area Network. The private network connecting computers within your office. Colleagues on the same LAN can access the application using its LAN URL without the application being exposed to the internet."],
      ["Ollama",            "The free, open-source program that runs AI models on your local computer. It operates invisibly in the background and must be running for the application to work."],
      ["OCR",               "Optical Character Recognition. The technology that reads text from scanned images or photographs of documents. Used automatically when the application encounters a scanned PDF."],
      ["Prompt",            "What you type into the chat box. Also called a query or question. A well-crafted prompt leads to a better, more focused answer."],
      ["RAG",               "Retrieval-Augmented Generation. The technical name for the approach this application uses: it retrieves relevant passages from your documents, then uses an AI model to generate an answer grounded in those passages rather than relying on general training knowledge."],
      ["Temperature",       "A setting that controls how creative or conservative the AI’s responses are. Lower values (closer to 0) produce more consistent, document-focused answers; higher values produce more varied, expressive prose."],
      ["Vector Store",      "The database where the application stores all the embeddings for your documents. It enables instant similarity searching across thousands of document chunks."],
    ],
    [2600, 6760]
  ),
  spacer(200),
  new Paragraph({ children: [new PageBreak()] }),
];

// ── Section 9 — Quick Reference ───────────────────────────────────────────────
const section9 = [
  h1("9.  Quick Reference Card"),
  rule(),
  body("Use this page as a quick reminder of the most common tasks."),
  spacer(120),

  h2("Creating a Knowledge Base"),
  numbered("Settings tab → “Add Knowledge Base” section."),
  numbered("Enter a name and the folder path."),
  numbered("Click “Add + Ingest Now.”"),
  numbered("Wait for the “✓ Done!” message. The table updates automatically."),
  spacer(120),

  h2("Starting a Chat Session"),
  numbered("Chat tab → check the KB(s) you need under “Active Knowledge Bases.”"),
  numbered("Choose a model from the dropdown."),
  numbered("Set Temperature to 0.1 for factual questions; 0.4 for drafting."),
  numbered("Type your question and press Enter or click Send."),
  spacer(120),

  h2("Re-indexing After Adding Documents"),
  numbered("Settings tab → “Modify a Knowledge Base.”"),
  numbered("Select the KB from the dropdown."),
  numbered("Click “↺ Re-index.”"),
  spacer(120),

  h2("Sharing the Application URL"),
  numbered("Settings tab → scroll to “App URLs.”"),
  numbered("Click the copy icon next to “Local / LAN URL.”"),
  numbered("Paste the URL into an email or message to your colleague."),
  spacer(120),

  h2("Checking the Ingestion Log"),
  numbered("Settings tab → scroll to the bottom."),
  numbered("Click “📋 View Ingestion Log File.”"),
  spacer(200),

  rule(GOLD),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 160, after: 80 },
    children: [new TextRun({ text: "Access to Justice — AI-Powered Legal Document Assistant", font: "Calibri", size: 20, italics: true, color: "888888" })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 80 },
    children: [new TextRun({ text: "Your documents stay on your machine. Always.", font: "Calibri", size: 20, italics: true, color: "888888" })],
  }),
];

// ── Assemble Document ─────────────────────────────────────────────────────────
const doc = new Document({
  numbering: {
    config: [
      {
        reference: "bullets",
        levels: [{
          level: 0, format: LevelFormat.BULLET, text: "•",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } },
        }, {
          level: 1, format: LevelFormat.BULLET, text: "◦",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 1080, hanging: 360 } } },
        }],
      },
      {
        reference: "steps",
        levels: [{
          level: 0, format: LevelFormat.DECIMAL, text: "%1.",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 400 } } },
        }],
      },
    ],
  },
  styles: {
    default: {
      document: { run: { font: "Calibri", size: 22 } },
    },
    paragraphStyles: [
      {
        id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 36, bold: true, font: "Calibri", color: NAVY },
        paragraph: { spacing: { before: 360, after: 160 }, outlineLevel: 0 },
      },
      {
        id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: "Calibri", color: BLUE },
        paragraph: { spacing: { before: 280, after: 120 }, outlineLevel: 1 },
      },
      {
        id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, font: "Calibri", color: NAVY },
        paragraph: { spacing: { before: 200, after: 100 }, outlineLevel: 2 },
      },
    ],
  },
  sections: [{
    properties: {
      page: {
        size: { width: PAGE_W, height: PAGE_H },
        margin: { top: MARGIN, right: MARGIN, bottom: MARGIN, left: MARGIN },
      },
    },
    headers: {
      default: new Header({
        children: [
          new Paragraph({
            border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: BLUE, space: 4 } },
            spacing: { after: 80 },
            children: [
              new TextRun({ text: "Access to Justice  —  User Guide", font: "Calibri", size: 18, color: "888888" }),
              new TextRun({ text: "       Confidential", font: "Calibri", size: 18, color: "BBBBBB", italics: true }),
            ],
          }),
        ],
      }),
    },
    footers: {
      default: new Footer({
        children: [
          new Paragraph({
            border: { top: { style: BorderStyle.SINGLE, size: 4, color: BLUE, space: 4 } },
            spacing: { before: 80 },
            children: [
              new TextRun({ text: "Version 1.0  •  June 2026", font: "Calibri", size: 18, color: "888888" }),
              new TextRun({ text: "\t\tPage ", font: "Calibri", size: 18, color: "888888" }),
              new TextRun({ children: [PageNumber.CURRENT], font: "Calibri", size: 18, color: "888888" }),
              new TextRun({ text: " of ", font: "Calibri", size: 18, color: "888888" }),
              new TextRun({ children: [PageNumber.TOTAL_PAGES], font: "Calibri", size: 18, color: "888888" }),
            ],
          }),
        ],
      }),
    },
    children: [
      ...coverPage,
      ...tocPage,
      ...section1,
      ...section2,
      ...section3,
      ...section4,
      ...section5,
      ...section6,
      ...section7,
      ...section8,
      ...section9,
    ],
  }],
});

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync("Access_to_Justice_User_Guide.docx", buffer);
  console.log("Done: Access_to_Justice_User_Guide.docx");
});
