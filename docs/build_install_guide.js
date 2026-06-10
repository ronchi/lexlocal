const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, PageNumber, PageBreak, TableOfContents, LevelFormat,
} = require("docx");
const fs = require("fs");

const NAVY="1F3864",BLUE="2E5FA3",LBLUE="D6E4F7",GOLD="C8A84B",LGOLD="FFF8E7";
const LGREEN="E8F5E9",GREEN="2E7D32";
const WIN_BG="EEF4FB",MAC_BG="F2F2F7",LNX_BG="FFF3E0";
const WIN_ACCENT="0078D4",MAC_ACCENT="555555",LNX_ACCENT="E65100";
const WHITE="FFFFFF",GRAY="F5F5F5",DGRAY="444444";
const CODE_BG="1E1E1E",CODE_FG="D4D4D4";

const inch=n=>Math.round(n*1440);
const PAGE_W=inch(8.5),PAGE_H=inch(11),MARGIN=inch(1);
const CONTENT_W=PAGE_W-MARGIN*2;

const cb=(color="BBBBBB")=>({
  top:{style:BorderStyle.SINGLE,size:1,color},
  bottom:{style:BorderStyle.SINGLE,size:1,color},
  left:{style:BorderStyle.SINGLE,size:1,color},
  right:{style:BorderStyle.SINGLE,size:1,color},
});
const nb=()=>({
  top:{style:BorderStyle.NONE,size:0,color:WHITE},
  bottom:{style:BorderStyle.NONE,size:0,color:WHITE},
  left:{style:BorderStyle.NONE,size:0,color:WHITE},
  right:{style:BorderStyle.NONE,size:0,color:WHITE},
});

const sp=(after=120)=>new Paragraph({spacing:{after},children:[new TextRun("")]});
const rule=(color=BLUE)=>new Paragraph({spacing:{after:120},border:{bottom:{style:BorderStyle.SINGLE,size:4,color,space:4}},children:[new TextRun("")]});

const body=(text,after=160)=>new Paragraph({spacing:{after,line:276},children:[new TextRun({text,font:"Calibri",size:22,color:DGRAY})]});

const bRuns=(runs,after=160)=>new Paragraph({spacing:{after,line:276},children:runs.map(r=>typeof r==="string"?new TextRun({text:r,font:"Calibri",size:22,color:DGRAY}):new TextRun({font:"Calibri",size:22,color:DGRAY,...r}))});

const bull=(text,level=0)=>new Paragraph({numbering:{reference:"bullets",level},spacing:{after:100,line:276},children:[new TextRun({text,font:"Calibri",size:22,color:DGRAY})]});

const stp=(text,ref="steps0")=>new Paragraph({numbering:{reference:ref,level:0},spacing:{after:140,line:276},children:[new TextRun({text,font:"Calibri",size:22,color:DGRAY})]});

const stpR=(runs,ref="steps0")=>new Paragraph({numbering:{reference:ref,level:0},spacing:{after:140,line:276},children:runs.map(r=>typeof r==="string"?new TextRun({text:r,font:"Calibri",size:22,color:DGRAY}):new TextRun({font:"Calibri",size:22,color:DGRAY,...r}))});

const h1=(text,color=NAVY)=>new Paragraph({heading:HeadingLevel.HEADING_1,spacing:{before:360,after:160},children:[new TextRun({text,font:"Calibri",size:36,bold:true,color})]});
const h2=(text,color=BLUE)=>new Paragraph({heading:HeadingLevel.HEADING_2,spacing:{before:280,after:120},children:[new TextRun({text,font:"Calibri",size:28,bold:true,color})]});
const h3=(text,color=NAVY)=>new Paragraph({heading:HeadingLevel.HEADING_3,spacing:{before:200,after:100},children:[new TextRun({text,font:"Calibri",size:24,bold:true,color})]});

const osBanner=(icon,title,subtitle,accent,bg)=>{
  const cell=new TableCell({
    borders:{top:{style:BorderStyle.SINGLE,size:12,color:accent},bottom:{style:BorderStyle.SINGLE,size:2,color:accent},left:{style:BorderStyle.SINGLE,size:2,color:accent},right:{style:BorderStyle.SINGLE,size:2,color:accent}},
    shading:{fill:bg,type:ShadingType.CLEAR},
    margins:{top:200,bottom:200,left:280,right:280},
    width:{size:CONTENT_W,type:WidthType.DXA},
    children:[
      new Paragraph({spacing:{after:40},children:[new TextRun({text:icon+"  "+title,font:"Calibri",size:48,bold:true,color:accent})]}),
      new Paragraph({spacing:{after:0},children:[new TextRun({text:subtitle,font:"Calibri",size:22,color:DGRAY,italics:true})]}),
    ],
  });
  return new Table({width:{size:CONTENT_W,type:WidthType.DXA},columnWidths:[CONTENT_W],rows:[new TableRow({children:[cell]})]});
};

const codeBlock=(lines)=>{
  const children=(Array.isArray(lines)?lines:[lines]).map(line=>new Paragraph({spacing:{after:0,line:240},children:[new TextRun({text:line,font:"Courier New",size:19,color:CODE_FG})]}));
  const codeCell=new TableCell({
    borders:{top:{style:BorderStyle.SINGLE,size:1,color:"444444"},bottom:{style:BorderStyle.SINGLE,size:1,color:"444444"},left:{style:BorderStyle.SINGLE,size:4,color:GOLD},right:{style:BorderStyle.SINGLE,size:1,color:"444444"}},
    shading:{fill:CODE_BG,type:ShadingType.CLEAR},
    margins:{top:120,bottom:120,left:200,right:200},
    width:{size:CONTENT_W,type:WidthType.DXA},
    children,
  });
  return new Table({width:{size:CONTENT_W,type:WidthType.DXA},columnWidths:[CONTENT_W],rows:[new TableRow({children:[codeCell]})]});
};

const code=(text)=>new TextRun({text,font:"Courier New",size:20,color:NAVY,bold:true});

const callout=(icon,label,labelColor,bgColor,topColor,paras)=>{
  const callCell=new TableCell({
    borders:{top:{style:BorderStyle.SINGLE,size:6,color:topColor},bottom:{style:BorderStyle.SINGLE,size:1,color:topColor},left:{style:BorderStyle.SINGLE,size:1,color:topColor},right:{style:BorderStyle.SINGLE,size:1,color:topColor}},
    shading:{fill:bgColor,type:ShadingType.CLEAR},
    margins:{top:120,bottom:120,left:180,right:180},
    width:{size:CONTENT_W,type:WidthType.DXA},
    children:[new Paragraph({spacing:{after:80},children:[new TextRun({text:icon+"  "+label,font:"Calibri",size:21,bold:true,color:labelColor})]}),...paras],
  });
  return new Table({width:{size:CONTENT_W,type:WidthType.DXA},columnWidths:[CONTENT_W],rows:[new TableRow({children:[callCell]})]});
};

const cbody=(text)=>new Paragraph({spacing:{after:80,line:270},children:[new TextRun({text,font:"Calibri",size:21,color:DGRAY})]});
const cbull=(text)=>new Paragraph({numbering:{reference:"bullets",level:0},spacing:{after:80,line:270},children:[new TextRun({text,font:"Calibri",size:21,color:DGRAY})]});

const tip=(...p)=>callout("\u{1F4A1}","Tip",GREEN,LGREEN,GREEN,p);
const note=(...p)=>callout("ℹ️","Note",BLUE,LBLUE,BLUE,p);
const warn=(...p)=>callout("⚠️","Important",GOLD,LGOLD,GOLD,p);

const dataTable=(headers,rows,colW)=>{
  const totalW=colW.reduce((a,b)=>a+b,0);
  const hRow=new TableRow({tableHeader:true,children:headers.map((h,i)=>new TableCell({
    borders:cb(NAVY),shading:{fill:NAVY,type:ShadingType.CLEAR},
    margins:{top:100,bottom:100,left:120,right:120},
    width:{size:colW[i],type:WidthType.DXA},
    children:[new Paragraph({spacing:{after:0},children:[new TextRun({text:h,font:"Calibri",size:20,bold:true,color:WHITE})]})],
  }))});
  const dRows=rows.map((row,ri)=>new TableRow({children:row.map((cell,ci)=>new TableCell({
    borders:cb("CCCCCC"),shading:{fill:ri%2===0?WHITE:GRAY,type:ShadingType.CLEAR},
    margins:{top:80,bottom:80,left:120,right:120},
    width:{size:colW[ci],type:WidthType.DXA},
    children:[new Paragraph({spacing:{after:0},children:typeof cell==="string"?[new TextRun({text:cell,font:"Calibri",size:20,color:DGRAY})]:cell})],
  }))}));
  return new Table({width:{size:totalW,type:WidthType.DXA},columnWidths:colW,rows:[hRow,...dRows]});
};

const PB=()=>new Paragraph({children:[new PageBreak()]});


// ── COVER ────────────────────────────────────────────────────────────────────
const cover=[
  sp(inch(0.9)),
  new Paragraph({alignment:AlignmentType.CENTER,spacing:{after:0},children:[new TextRun({text:"ACCESS TO JUSTICE",font:"Calibri",size:64,bold:true,color:NAVY})]}),
  new Paragraph({alignment:AlignmentType.CENTER,spacing:{after:80},children:[new TextRun({text:"AI-Powered Legal Document Assistant",font:"Calibri",size:30,color:BLUE,italics:true})]}),
  new Paragraph({alignment:AlignmentType.CENTER,spacing:{after:560},border:{bottom:{style:BorderStyle.SINGLE,size:6,color:GOLD,space:8}},children:[new TextRun("")]}),
  sp(360),
  new Paragraph({alignment:AlignmentType.CENTER,spacing:{after:120},children:[new TextRun({text:"Installation & Setup Guide",font:"Calibri",size:44,bold:true,color:DGRAY})]}),
  new Paragraph({alignment:AlignmentType.CENTER,spacing:{after:240},children:[new TextRun({text:"Windows 11  •  macOS  •  Linux",font:"Calibri",size:28,color:BLUE})]}),
  sp(480),
  new Paragraph({alignment:AlignmentType.CENTER,spacing:{after:60},children:[new TextRun({text:"Version 1.0   •   June 2026",font:"Calibri",size:22,color:"888888"})]}),
  new Paragraph({alignment:AlignmentType.CENTER,spacing:{after:60},children:[new TextRun({text:"Step-by-step instructions for all three platforms",font:"Calibri",size:22,color:"888888",italics:true})]}),
  PB(),
];

// ── TOC ──────────────────────────────────────────────────────────────────────
const toc=[
  h1("Table of Contents"),
  new TableOfContents("Table of Contents",{hyperlink:true,headingStyleRange:"1-3"}),
  PB(),
];

// ── INTRO ───────────────────────────────────────────────────────────────────
const intro=[
  h1("1.  Before You Begin"),
  rule(),
  body("This guide walks you through installing and running the Access to Justice application on three operating systems: Windows 11, macOS, and Linux. Each platform has its own dedicated section -- you only need to follow the section for your computer."),
  sp(120),
  body("The installation involves four components, all of which are free and open source:"),
  sp(60),
  dataTable(
    ["Component","What It Is","Who Installs It"],
    [
      ["Python 3.11+","The programming language the application is written in.","You (following this guide)"],
      ["Ollama","Runs AI models locally on your computer. Required for all AI features.","You (following this guide)"],
      ["AI Models","The language models Ollama will use (e.g., Llama 3.3, nomic-embed-text).","You (one command)"],
      ["Application Files","The Access to Justice application itself.","Provided by your IT contact or firm"],
    ],
    [2200,4200,2960]
  ),
  sp(160),
  h2("1.1  Hardware Requirements"),
  body("The application runs entirely on your own computer. Performance depends on your hardware:"),
  sp(60),
  dataTable(
    ["Component","Minimum","Recommended"],
    [
      ["RAM (Memory)","16 GB","32 GB or more"],
      ["Storage","20 GB free","50 GB free (AI models are large)"],
      ["Processor","Modern quad-core CPU","Apple Silicon (M1/M2/M3) or GPU-equipped PC for faster AI"],
      ["Internet","Required during installation only","Not required after setup -- all AI runs locally"],
    ],
    [2400,2880,4080]
  ),
  sp(160),
  warn(
    cbody("AI models are large files. The recommended Llama 3.3 70B model alone is approximately 43 GB. Plan for a reliable internet connection during the initial download and ensure you have sufficient disk space before beginning.")
  ),
  sp(120),
  h2("1.2  Estimated Installation Time"),
  dataTable(
    ["Task","Approximate Time"],
    [
      ["Installing Python, Windows Terminal / Homebrew","5-10 minutes"],
      ["Installing Ollama","5 minutes"],
      ["Downloading AI models (depends on internet speed)","20 minutes - 2 hours"],
      ["Installing application Python dependencies","5-15 minutes"],
      ["Total","30 minutes to 2+ hours (mostly waiting for downloads)"],
    ],
    [5000,4360]
  ),
  sp(120),
  PB(),
];

// ── WINDOWS ─────────────────────────────────────────────────────────────────
const windows=[
  osBanner("🪟","Part A -- Windows 11","Step-by-step installation for Windows 11",WIN_ACCENT,WIN_BG),
  sp(160),
  body("Windows 11 requires a few tools to be installed before the application can run. Follow each step in order. All software used here is free."),
  sp(120),
  h2("A.1  Install Windows Terminal"),
  body("Windows Terminal is a modern, tabbed command-line application. It is the tool you will use to type the commands in this guide. It is far easier to use than the older Command Prompt."),
  sp(80),
  stp("Click the Start button (the Windows logo) at the bottom of your screen.","steps0"),
  stp("Type: Microsoft Store and press Enter.","steps0"),
  stp("Search for Windows Terminal. Click the result published by Microsoft."),
  stp("Click Get (or Install). It will download and install automatically.","steps0"),
  stp("Once installed, click Open. A dark window with a command prompt will appear. Keep it open throughout this installation.","steps0"),
  sp(120),
  tip(
    cbody("To open Windows Terminal later: right-click on the Desktop or inside any folder in File Explorer and choose Open in Terminal. Alternatively, press the Windows key, type terminal, and press Enter.")
  ),
  sp(120),
  h2("A.2  Install Python 3.11"),
  body("Python is the programming language that powers the application. It must be installed from the official Python website -- do not use the version in the Microsoft Store, as it has limitations."),
  sp(80),
  stp("Open your web browser and go to: https://www.python.org/downloads/","steps0"),
  stp("Click the yellow Download Python 3.x.x button (any version 3.11 or higher is fine)."),
  stp("Run the downloaded installer (.exe file).","steps0"),
  warn(
    cbody("On the very first screen of the installer, you will see a checkbox that says Add Python to PATH. You MUST check this box before clicking Install Now. If you miss this step, Python commands will not work in the terminal.")
  ),
  sp(80),
  stp("Check Add python.exe to PATH, then click Install Now."),
  stp("Wait for the installation to finish, then click Close.","steps0"),
  stp("Verify the installation. In Windows Terminal, type the following and press Enter:","steps0"),
  sp(40),
  codeBlock("python --version"),
  sp(80),
  bRuns(["You should see a response like ",code("Python 3.11.9"),". If you see an error, close and reopen Windows Terminal and try again."]),
  sp(120),
  h2("A.3  Allow PowerShell Scripts (One-Time Setup)"),
  body("Windows Terminal uses PowerShell by default, which blocks scripts from running. This would prevent the virtual environment from activating. You need to change this setting once."),
  sp(80),
  stp("In Windows Terminal, type the following and press Enter:","steps0"),
  sp(40),
  codeBlock("Set-ExecutionPolicy RemoteSigned -Scope CurrentUser"),
  sp(80),
  stp("You will be asked to confirm. Type Y and press Enter."),
  sp(120),
  note(
    cbody("This change only affects your own user account. It allows scripts you have downloaded yourself to run -- it does not reduce security for other users or system-wide operations.")
  ),
  sp(120),
  h2("A.4  Install Ollama for Windows"),
  body("Ollama is the program that runs AI models locally. It installs as a regular Windows application."),
  sp(80),
  stp("Open your web browser and go to: https://ollama.com/download","steps0"),
  bRuns(["Click ",{text:"Download for Windows",bold:true},". Run the downloaded ",code("OllamaSetup.exe")," file."]),
  stp("Follow the installation wizard using the default options. Click Next, then Install, then Finish.","steps0"),
  stp("After installation, Ollama starts automatically. A small llama icon will appear in your system tray (near the clock at the bottom-right of your screen).","steps0"),
  stp("Verify Ollama is running. In Windows Terminal, type:","steps0"),
  sp(40),
  codeBlock("ollama --version"),
  sp(80),
  body("You should see a version number. If the command is not found, close and reopen Windows Terminal."),
  sp(120),
  h2("A.5  Download the Required AI Models"),
  body("You need two models: one for searching your documents (the embedding model) and one for answering questions and drafting (the chat model). These are large downloads."),
  sp(80),
  stp("In Windows Terminal, type each command below and press Enter. Wait for each download to complete before running the next:","steps0"),
  sp(40),
  codeBlock([
    "ollama pull nomic-embed-text",
    "",
    "ollama pull llama3.3:70b",
  ]),
  sp(80),
  warn(
    cbody("The llama3.3:70b model is approximately 43 GB. On a typical home internet connection this may take 1-2 hours. You can continue to the next steps while it downloads in a separate terminal window.")
  ),
  sp(80),
  tip(
    cbody("If 43 GB is too large for your storage, a smaller alternative is mistral (4.1 GB) or llama3.2:3b (2 GB). These are less capable for complex legal work but will run on modest hardware. Run: ollama pull mistral")
  ),
  sp(120),
  h2("A.6  Copy the Application Files"),
  bRuns(["Place the Access to Justice application folder somewhere convenient -- for example: ",code("C:\\Users\\YourName\\Documents\\access_to_justice"),"."]),
  sp(80),
  stp("In Windows Terminal, navigate to the application folder. Replace the path with the actual location on your computer:","steps0"),
  sp(40),
  codeBlock('cd "C:\\Users\\YourName\\Documents\\access_to_justice"'),
  sp(80),
  stp("Confirm you are in the right place by typing:","steps0"),
  sp(40),
  codeBlock("dir"),
  sp(80),
  bRuns(["You should see files including ",code("app.py"),", ",code("requirements.txt"),", and ",code("config.py"),"."]),
  sp(120),
  h2("A.7  Create a Virtual Environment"),
  body("A virtual environment is a self-contained Python installation for this application. It keeps the application's dependencies separate from anything else on your computer."),
  sp(80),
  stp("In Windows Terminal (still in the application folder), type:","steps0"),
  sp(40),
  codeBlock("python -m venv .venv"),
  sp(80),
  stp("Activate the virtual environment:","steps0"),
  sp(40),
  codeBlock(".venv\\Scripts\\Activate.ps1"),
  sp(80),
  bRuns(["Your terminal prompt will change to show ",code("(.venv)")," at the beginning. You must activate it every time you open a new terminal window to run the application."]),
  sp(120),
  h2("A.8  Install Application Dependencies"),
  body("This step downloads and installs all the Python libraries the application needs. It only needs to be done once."),
  sp(80),
  stp("With the virtual environment active, type:","steps0"),
  sp(40),
  codeBlock("pip install -r requirements.txt"),
  sp(80),
  body("This may take 5-15 minutes. Wait until you see a line ending in Successfully installed... before continuing."),
  sp(120),
  note(
    cbody("If any package fails with an error about Microsoft Visual C++, you may need the free C++ Build Tools. Download them from: https://visualstudio.microsoft.com/visual-cpp-build-tools/ -- choose Desktop development with C++ during installation, then re-run the pip install command.")
  ),
  sp(120),
  h2("A.9  Run the Application"),
  stp("Make sure Windows Terminal is in the application folder with the virtual environment active (you see (.venv) in your prompt).","steps0"),
  stp("Type the following command and press Enter:","steps0"),
  sp(40),
  codeBlock("python app.py"),
  sp(80),
  bRuns(["Open your web browser and go to: ",code("http://localhost:7860"),". The Access to Justice application will load."]),
  sp(80),
  tip(
    cbody("To allow colleagues on the same office network to use the application, start it with:  python app.py --lan")
  ),
  sp(120),
  h3("Stopping the Application"),
  body("To stop the application, go back to Windows Terminal and press Ctrl + C. The application will shut down."),
  sp(120),
  h3("Starting the Application in Future Sessions"),
  body("Each time you want to run the application, open Windows Terminal and run these commands:"),
  sp(40),
  codeBlock([
    'cd "C:\\Users\\YourName\\Documents\\access_to_justice"',
    ".venv\\Scripts\\Activate.ps1",
    "python app.py",
  ]),
  sp(120),
  PB(),
];

// ── macOS ────────────────────────────────────────────────────────────────────
const macos=[
  osBanner("🍎","Part B -- macOS","Step-by-step installation for macOS (Intel and Apple Silicon)",MAC_ACCENT,MAC_BG),
  sp(160),
  body("These instructions work for both Intel Macs and Apple Silicon (M1, M2, M3) Macs."),
  sp(120),
  h2("B.1  Install Command Line Developer Tools"),
  body("macOS needs its Command Line Developer Tools installed before Python packages can be compiled. This is a one-time step."),
  sp(80),
  stp("Open the Terminal application. Press Command + Space, type Terminal, and press Enter."),
  stp("Type the following command and press Enter:","steps0"),
  sp(40),
  codeBlock("xcode-select --install"),
  sp(80),
  stp("A dialog box will appear asking you to install the tools. Click Install and agree to the license. The download is about 500 MB and takes a few minutes.","steps0"),
  stp("When installation is complete, click Done.","steps0"),
  sp(120),
  h2("B.2  Install Homebrew"),
  body("Homebrew is the most popular package manager for macOS. It makes installing Python and other tools simple. If you already have Homebrew installed, skip to step 4 to verify it."),
  sp(80),
  stp("In Terminal, paste the following command and press Enter:","steps0"),
  sp(40),
  codeBlock('/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'),
  sp(80),
  stp("The installer will prompt for your Mac login password. Type it and press Enter. You will not see any characters appear -- this is normal.","steps0"),
  stp("Wait for installation to complete (several minutes).","steps0"),
  stp("Apple Silicon Macs only: after installation, Homebrew will show two commands beginning with echo and eval. Copy and run both. They configure your shell to find Homebrew."),
  stp("Verify Homebrew is installed:","steps0"),
  sp(40),
  codeBlock("brew --version"),
  sp(120),
  h2("B.3  Install Python 3.11"),
  body("We recommend installing the latest Python via Homebrew for best compatibility."),
  sp(80),
  stp("In Terminal, type:","steps0"),
  sp(40),
  codeBlock("brew install python@3.11"),
  sp(80),
  stp("Verify:","steps0"),
  sp(40),
  codeBlock("python3 --version"),
  sp(80),
  bRuns(["You should see ",code("Python 3.11.x")," or higher."]),
  sp(120),
  note(
    cbody("On macOS, the command is python3 (not python). This is because macOS ships with an older Python 2 that should be left untouched. All commands in this section use python3 and pip3.")
  ),
  sp(120),
  h2("B.4  Install Ollama for macOS"),
  body("Ollama for macOS installs as a regular application that runs in your menu bar."),
  sp(80),
  stp("Open your web browser and go to: https://ollama.com/download","steps0"),
  bRuns(["Click ",{text:"Download for Mac",bold:true},". Open the downloaded ",code(".dmg")," file."]),
  stp("Drag the Ollama icon into your Applications folder.","steps0"),
  stp("Open Ollama from Applications. A small llama icon will appear in your menu bar.","steps0"),
  stp("Verify Ollama is running:","steps0"),
  sp(40),
  codeBlock("ollama --version"),
  sp(120),
  h2("B.5  Download the Required AI Models"),
  stp("In Terminal, run each command and wait for it to complete before running the next:","steps0"),
  sp(40),
  codeBlock([
    "ollama pull nomic-embed-text",
    "",
    "ollama pull llama3.3:70b",
  ]),
  sp(80),
  warn(
    cbody("The llama3.3:70b model is approximately 43 GB. Apple Silicon Macs (M1/M2/M3) run this model significantly faster than Intel Macs. On an M-series Mac, responses typically arrive in seconds; on an older Intel Mac, responses may take a minute or more.")
  ),
  sp(80),
  tip(
    cbody("Apple Silicon Macs with 16 GB of unified memory can run Llama 3.3 70B comfortably. On a Mac with only 8 GB, consider using the smaller mistral model: ollama pull mistral")
  ),
  sp(120),
  h2("B.6  Copy the Application Files"),
  bRuns(["Place the Access to Justice folder somewhere convenient -- for example: ",code("~/Documents/access_to_justice"),". Then navigate to it:"]),
  sp(40),
  codeBlock("cd ~/Documents/access_to_justice"),
  sp(80),
  bRuns(["Confirm you are in the right folder: type ",code("ls"),". You should see ",code("app.py"),", ",code("requirements.txt"),", and ",code("config.py"),"."]),
  sp(120),
  h2("B.7  Create a Virtual Environment"),
  sp(40),
  codeBlock("python3 -m venv .venv"),
  sp(80),
  stp("Activate it:","steps0"),
  sp(40),
  codeBlock("source .venv/bin/activate"),
  sp(80),
  bRuns(["Your terminal prompt will change to show ",code("(.venv)")," at the beginning. You must activate it each time you open a new Terminal window."]),
  sp(120),
  h2("B.8  Install Application Dependencies"),
  sp(40),
  codeBlock("pip install -r requirements.txt"),
  sp(80),
  body("Wait for all packages to finish. This may take 5-15 minutes."),
  sp(120),
  h2("B.9  Run the Application"),
  stp("With the virtual environment active, type:","steps0"),
  sp(40),
  codeBlock("python app.py"),
  sp(80),
  bRuns(["Open your browser and navigate to: ",code("http://localhost:7860"),"."]),
  sp(80),
  tip(
    cbody("For LAN access (so colleagues can connect): python app.py --lan   To find your Mac IP address: go to System Settings > Network > Wi-Fi and look for the IP Address field.")
  ),
  sp(120),
  h3("Stopping the Application"),
  body("Press Control + C in Terminal to stop the application."),
  sp(120),
  h3("Starting the Application in Future Sessions"),
  sp(40),
  codeBlock([
    "cd ~/Documents/access_to_justice",
    "source .venv/bin/activate",
    "python app.py",
  ]),
  sp(120),
  PB(),
];

// ── LINUX ────────────────────────────────────────────────────────────────────
const linux=[
  osBanner("🐧","Part C -- Linux","Step-by-step installation for Ubuntu 22.04 / 24.04 LTS and compatible distributions",LNX_ACCENT,LNX_BG),
  sp(160),
  body("These instructions are written for Ubuntu 22.04 LTS and 24.04 LTS. They also work with minimal changes on Debian, Linux Mint, and Pop!_OS."),
  sp(120),
  h2("C.1  Update Your System"),
  body("Before installing anything, update your package lists to ensure you get the latest versions."),
  sp(80),
  stp("Open a Terminal window (Ctrl + Alt + T on most distributions).","steps0"),
  stp("Type the following commands, pressing Enter after each. You will be prompted for your password:","steps0"),
  sp(40),
  codeBlock([
    "sudo apt update",
    "sudo apt upgrade -y",
  ]),
  sp(120),
  h2("C.2  Install Python and System Packages"),
  body("Ubuntu 22.04 ships with Python 3.10 and Ubuntu 24.04 with Python 3.12. Both work. The commands below also install system libraries required by the application."),
  sp(80),
  stp("Install Python and dependencies:","steps0"),
  sp(40),
  codeBlock([
    "sudo apt install -y python3 python3-pip python3-venv python3-dev \\",
    "    build-essential libssl-dev libffi-dev \\",
    "    libgl1 libglib2.0-0 libsm6 libxext6",
  ]),
  sp(80),
  stp("Verify Python is installed:","steps0"),
  sp(40),
  codeBlock("python3 --version"),
  sp(120),
  note(
    cbody("On Ubuntu 22.04, if you specifically need Python 3.11, add the deadsnakes PPA first: sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt update && sudo apt install python3.11 python3.11-venv python3.11-dev. Then replace python3 with python3.11 in subsequent commands.")
  ),
  sp(120),
  note(
    cbody("Fedora / RHEL / Rocky Linux: replace apt with dnf. For example: sudo dnf install python3 python3-pip python3-virtualenv gcc")
  ),
  sp(120),
  h2("C.3  Install Ollama"),
  body("Ollama provides an official install script for Linux that handles everything automatically."),
  sp(80),
  stp("Run the official Ollama install script:","steps0"),
  sp(40),
  codeBlock("curl -fsSL https://ollama.com/install.sh | sh"),
  sp(80),
  stp("The script installs Ollama and sets it up as a system service. Verify it is running:","steps0"),
  sp(40),
  codeBlock("ollama --version"),
  sp(80),
  stp("Start the Ollama service if not already running:","steps0"),
  sp(40),
  codeBlock("sudo systemctl start ollama"),
  sp(80),
  stp("Optional -- enable Ollama to start automatically on boot:","steps0"),
  sp(40),
  codeBlock("sudo systemctl enable ollama"),
  sp(120),
  note(
    cbody("If you have an NVIDIA GPU, Ollama will detect and use it automatically for significantly faster AI responses. Make sure your NVIDIA drivers are installed before running the Ollama install script.")
  ),
  sp(120),
  h2("C.4  Download the Required AI Models"),
  stp("Pull the embedding model and chat model:","steps0"),
  sp(40),
  codeBlock([
    "ollama pull nomic-embed-text",
    "",
    "ollama pull llama3.3:70b",
  ]),
  sp(80),
  warn(
    cbody("The llama3.3:70b model is approximately 43 GB. If disk space is limited, consider the smaller mistral model (4.1 GB): ollama pull mistral")
  ),
  sp(120),
  h2("C.5  Copy the Application Files"),
  bRuns(["Place the Access to Justice folder at a convenient location -- for example: ",code("~/access_to_justice"),". Then navigate to it:"]),
  sp(40),
  codeBlock("cd ~/access_to_justice"),
  sp(80),
  bRuns(["Verify the files are present with ",code("ls"),". You should see ",code("app.py"),", ",code("requirements.txt"),", and ",code("config.py"),"."]),
  sp(120),
  h2("C.6  Create a Virtual Environment"),
  sp(40),
  codeBlock([
    "python3 -m venv .venv",
    "source .venv/bin/activate",
  ]),
  sp(80),
  bRuns(["Your prompt will change to show ",code("(.venv)"),"."]),
  sp(120),
  h2("C.7  Install Application Dependencies"),
  sp(40),
  codeBlock("pip install -r requirements.txt"),
  sp(80),
  body("Wait for the Successfully installed message before continuing."),
  sp(120),
  h2("C.8  Run the Application"),
  stp("With the virtual environment active, start the application:","steps0"),
  sp(40),
  codeBlock("python app.py"),
  sp(80),
  bRuns(["Open a browser and navigate to: ",code("http://localhost:7860"),"."]),
  sp(80),
  tip(
    cbody("For LAN access: python app.py --lan   Find your IP address with: hostname -I | awk {print $1}   Share that address with colleagues: http://<your-ip>:7860")
  ),
  sp(120),
  h3("Starting the Application in Future Sessions"),
  sp(40),
  codeBlock([
    "cd ~/access_to_justice",
    "source .venv/bin/activate",
    "python app.py",
    "",
    "# If Ollama is not running:",
    "sudo systemctl start ollama",
  ]),
  sp(120),
  PB(),
];

// ── VERIFY & TROUBLESHOOT ────────────────────────────────────────────────────
const verify=[
  h1("2.  Verifying Your Installation"),
  rule(),
  body("After completing the installation for your operating system, follow these steps to confirm everything is working."),
  sp(120),
  h2("2.1  Check the Application Loads"),
  stp("Start the application (see the Run the Application section for your OS).","steps0"),
  bRuns(["Open a browser and go to ",code("http://localhost:7860"),"."]),
  stp("You should see the Access to Justice interface with two tabs.","steps0"),
  sp(120),
  h2("2.2  Test the Ollama Connection"),
  stp("Click the Settings & Knowledge Bases tab."),
  stp("Click the Test Connection button.","steps0"),
  stp("You should see: Connected. X model(s) available.","steps0"),
  sp(80),
  warn(
    cbody("If the connection test fails, Ollama is not running. On macOS, look for the llama icon in the menu bar. On Windows, look in the system tray. On Linux, run: sudo systemctl start ollama")
  ),
  sp(120),
  h2("2.3  Test Document Ingestion"),
  stp("Create a test folder containing one or two PDF or Word documents.","steps0"),
  stp("In the Settings tab, enter a name (e.g., Test) and the path to your test folder.","steps0"),
  stp("Click Add + Ingest Now and watch the progress log.","steps0"),
  stp("When done, the Knowledge Bases table should show Indexed next to your test KB.","steps0"),
  sp(120),
  h2("2.4  Test the Chat"),
  stp("Click the Chat tab.","steps0"),
  stp("Check the Test KB checkbox.","steps0"),
  stp("Type a simple question and press Enter.","steps0"),
  stp("You should see status messages followed by a text response.","steps0"),
  sp(120),
  PB(),
];

const troubleshoot=[
  h1("3.  Troubleshooting by Platform"),
  rule(),
  sp(80),
  h2("3.1  Windows 11"),
  dataTable(
    ["Problem","Cause","Solution"],
    [
      ["python is not recognized",
       "Python was not added to PATH during installation.",
       "Uninstall Python and reinstall it, making sure to check Add python.exe to PATH on the first installer screen."],
      ["Activate.ps1 cannot be loaded",
       "PowerShell execution policy is blocking scripts.",
       "Run: Set-ExecutionPolicy RemoteSigned -Scope CurrentUser  Type Y when prompted."],
      ["pip install fails: Microsoft Visual C++ required",
       "Some packages need a C++ compiler.",
       "Install Microsoft C++ Build Tools from: https://visualstudio.microsoft.com/visual-cpp-build-tools/ and choose Desktop development with C++."],
      ["Ollama icon not in system tray",
       "Ollama did not start after installation.",
       "Open the Start menu, search for Ollama, and click to launch it."],
    ],
    [2400,2760,4200]
  ),
  sp(160),
  h2("3.2  macOS"),
  dataTable(
    ["Problem","Cause","Solution"],
    [
      ["brew: command not found",
       "Homebrew was not added to the shell PATH (common on Apple Silicon).",
       "Run the two echo and eval commands shown at the end of the Homebrew installation, then restart Terminal."],
      ["pip install fails: command gcc failed",
       "Command Line Developer Tools are missing.",
       "Run: xcode-select --install  Then retry pip install."],
      ["Ollama menu bar icon is missing",
       "Ollama was not opened from Applications.",
       "Open Finder > Applications > Ollama and double-click it."],
      ["Very slow AI responses on Intel Mac",
       "Intel Macs run AI models on the CPU, which is slower than Apple Silicon.",
       "Use a smaller model: ollama pull mistral"],
    ],
    [2400,2760,4200]
  ),
  sp(160),
  h2("3.3  Linux"),
  dataTable(
    ["Problem","Cause","Solution"],
    [
      ["python3-venv not found",
       "The venv package is not installed.",
       "Run: sudo apt install python3-venv"],
      ["curl: command not found",
       "curl is not installed.",
       "Run: sudo apt install curl  Then retry the Ollama install command."],
      ["ollama.service failed to start",
       "Port 11434 may be in use by another process.",
       "Check errors with: sudo journalctl -u ollama -n 50"],
      ["EasyOCR install fails with CUDA errors",
       "EasyOCR tries to install a GPU version of PyTorch.",
       "Run first: pip install torch --index-url https://download.pytorch.org/whl/cpu  Then retry requirements.txt"],
    ],
    [2400,2760,4200]
  ),
  sp(120),
  PB(),
];

const quickRef=[
  h1("4.  Quick-Start Reference"),
  rule(),
  body("Once installation is complete, use these commands each time you want to start the application."),
  sp(120),
  h2("Windows 11"),
  codeBlock([
    "# Open Windows Terminal, then:",
    'cd "C:\\Users\\YourName\\Documents\\access_to_justice"',
    ".venv\\Scripts\\Activate.ps1",
    "python app.py",
    "",
    "# LAN mode (accessible to colleagues on your network):",
    "python app.py --lan",
  ]),
  sp(120),
  h2("macOS"),
  codeBlock([
    "# Open Terminal, then:",
    "cd ~/Documents/access_to_justice",
    "source .venv/bin/activate",
    "python app.py",
    "",
    "# LAN mode:",
    "python app.py --lan",
  ]),
  sp(120),
  h2("Linux"),
  codeBlock([
    "# Open Terminal, then:",
    "cd ~/access_to_justice",
    "source .venv/bin/activate",
    "python app.py",
    "",
    "# LAN mode:",
    "python app.py --lan",
    "",
    "# If Ollama is not running:",
    "sudo systemctl start ollama",
  ]),
  sp(120),
  h2("Useful Ollama Commands (All Platforms)"),
  dataTable(
    ["Command","What It Does"],
    [
      ["ollama list","Lists all AI models installed on your computer."],
      ["ollama pull llama3.3:70b","Downloads (or updates) the Llama 3.3 70B model."],
      ["ollama pull nomic-embed-text","Downloads (or updates) the embedding model."],
      ["ollama pull mistral","Downloads the smaller, faster Mistral model."],
      ["ollama rm llama3.3:70b","Removes a model to free up disk space."],
      ["ollama serve","Manually starts the Ollama server if it is not running."],
    ],
    [3600,5760]
  ),
  sp(160),
  new Paragraph({alignment:AlignmentType.CENTER,spacing:{before:160,after:80},children:[new TextRun({text:"Access to Justice -- Installation Guide",font:"Calibri",size:20,italics:true,color:"888888"})]}),
  new Paragraph({alignment:AlignmentType.CENTER,spacing:{after:80},children:[new TextRun({text:"Your documents stay on your machine. Always.",font:"Calibri",size:20,italics:true,color:"888888"})]}),
];


// ── Assemble ─────────────────────────────────────────────────────────────────
const doc=new Document({
  numbering:{config:[
    {reference:"bullets",levels:[
      {level:0,format:LevelFormat.BULLET,text:"•",alignment:AlignmentType.LEFT,style:{paragraph:{indent:{left:720,hanging:360}}}},
      {level:1,format:LevelFormat.BULLET,text:"◦",alignment:AlignmentType.LEFT,style:{paragraph:{indent:{left:1080,hanging:360}}}},
    ]},
    {reference:"steps0",levels:[{level:0,format:LevelFormat.DECIMAL,text:"%1.",alignment:AlignmentType.LEFT,style:{paragraph:{indent:{left:720,hanging:400}}}}]},
  ]},
  styles:{
    default:{document:{run:{font:"Calibri",size:22}}},
    paragraphStyles:[
      {id:"Heading1",name:"Heading 1",basedOn:"Normal",next:"Normal",quickFormat:true,run:{size:36,bold:true,font:"Calibri",color:NAVY},paragraph:{spacing:{before:360,after:160},outlineLevel:0}},
      {id:"Heading2",name:"Heading 2",basedOn:"Normal",next:"Normal",quickFormat:true,run:{size:28,bold:true,font:"Calibri",color:BLUE},paragraph:{spacing:{before:280,after:120},outlineLevel:1}},
      {id:"Heading3",name:"Heading 3",basedOn:"Normal",next:"Normal",quickFormat:true,run:{size:24,bold:true,font:"Calibri",color:NAVY},paragraph:{spacing:{before:200,after:100},outlineLevel:2}},
    ],
  },
  sections:[{
    properties:{page:{size:{width:PAGE_W,height:PAGE_H},margin:{top:MARGIN,right:MARGIN,bottom:MARGIN,left:MARGIN}}},
    headers:{default:new Header({children:[new Paragraph({border:{bottom:{style:BorderStyle.SINGLE,size:4,color:BLUE,space:4}},spacing:{after:80},children:[new TextRun({text:"Access to Justice  --  Installation Guide",font:"Calibri",size:18,color:"888888"}),new TextRun({text:"   Windows 11  •  macOS  •  Linux",font:"Calibri",size:18,color:"BBBBBB"})]})]})},
    footers:{default:new Footer({children:[new Paragraph({border:{top:{style:BorderStyle.SINGLE,size:4,color:BLUE,space:4}},spacing:{before:80},children:[new TextRun({text:"Version 1.0  •  June 2026",font:"Calibri",size:18,color:"888888"}),new TextRun({text:"\t\tPage ",font:"Calibri",size:18,color:"888888"}),new TextRun({children:[PageNumber.CURRENT],font:"Calibri",size:18,color:"888888"}),new TextRun({text:" of ",font:"Calibri",size:18,color:"888888"}),new TextRun({children:[PageNumber.TOTAL_PAGES],font:"Calibri",size:18,color:"888888"})]})]})},
    children:[...cover,...toc,...intro,...windows,...macos,...linux,...verify,...troubleshoot,...quickRef],
  }],
});

Packer.toBuffer(doc).then(buf=>{
  fs.writeFileSync("Access_to_Justice_Installation_Guide.docx",buf);
  console.log("Done: Access_to_Justice_Installation_Guide.docx");
});
