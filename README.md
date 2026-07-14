# ResearchParça

Live Demo (read-only HTML export): [ResearchParça](https://zidrewndacht.github.io/bibtex-custom-parser).  
**Also check ResearchParça Lite (Minimal, generic PDF organizer/annotator):** [ResearchParça-Lite](https://github.com/Zidrewndacht/ResearchParsa-lite)

*The frontend was mostly tested with Mozilla Firefox and works well. The HTML export has known performance issues in Chromium‑based browsers. If the page lags or stops responding on reasonably modern hardware, please use Firefox instead.*

ResearchParça is a tool for managing and analysing a bibliographic database of academic papers, specifically tailored for **Printed Circuit Board (PCB) inspection**. It imports BibTeX files into an SQLite database and provides a rich web interface for browsing, filtering, editing, and performing **LLM‑driven classification and verification** of papers.

The system is designed to streamline literature reviews by offering advanced search, statistical analysis, and traceable AI‑enriched metadata.

## Features

- **BibTeX / CSV Import**  
  Import `.bib` files or IEEE Xplore CSV exports directly from the web interface. Duplicate detection prevents re‑import (based on DOI and title/year matching).

- **Web Interface**  
  A Flask‑based web application (`browse_db.py`) with an interactive table. Sort, filter and edit paper metadata.

- **LLM‑Powered Classification & Verification**  
  A separate **queue manager** (`queue_manager.py`) coordinates communication with an **OpenAI‑compatible LLM server** (mostly tested with vLLM, which allows for high concurrency which the task is exceedingly friendly for).  
  - Each paper is classified **three times independently** using a detailed prompt template.  
  - Results (including the model’s reasoning trace) are stored per set.  
  - A **verifier** LLM later scores the classification accuracy.  
  - An advanced **“Consensus” mode** iteratively re‑classifies misclassified papers until the verifier agrees (or a limit is reached).  

- **Advanced Filtering & Search**  
  Server‑side filters for year range and minimum page count; client‑side filtering for dozens of classification fields, including quick toggles for “Survey only”, “SMT only”, “Dataset available”, and custom tri‑state filters. The search bar indexes all relevant fields (title, abstract, authors, keywords, user comments).

- **Comprehensive Statistics & Visualisations**  
  A dedicated “View Statistics” modal (triggered by the **Stats** button) presents dynamic charts and lists based on the **currently visible** papers:
  - Repeating journals, conferences, keywords, authors, research areas, and mentioned models.
  - Keyword cloud.
  - Distribution charts for publication types, survey vs. primary papers, techniques, and features (with cumulative/stacked toggles).
  - Histograms of relevance and verifier scores.
  - Metrics: off‑topic ratio, SMT vs. THT, PDF presence, etc.

- **Data Editing**  
  Click any status symbol (✔️ / ❌ / ❔) to cycle its value – changes are saved instantly. In the expanded detail row, edit text fields (Research Area, Model Name, Other Defects, Page Count, Relevance, User Comments) and save manually.

- **PDF Management**  
  Upload, store, and view PDFs. An integrated, branded **PDF.js** annotator lets you highlight, draw, and add text notes – annotations are **auto‑saved** to the server after 5 seconds of inactivity. The PDF icon changes to indicate annotated versions.

- **Data Export**  
  - **Static HTML Export**: A self‑contained, compressed HTML file with full filtering, sorting, and charting capabilities – ideal for sharing or archiving.  
  - **XLSX Export**: (Currently outdated/disabled; may be re‑enabled in future releases) – originally offered formatted Excel spreadsheets.

- **Backup & Restore**  
  Create a complete backup (`.parça.zst` file) containing the SQLite database, all original and annotated PDFs, and the HTML export. Restore seamlessly from a previous backup – the current data is automatically backed up before overwriting.

- **History & Traceability**  
  Every classification, verification, and user edit is logged. The “History” button opens a detailed view with per‑set logs, change highlighting, and certainty indicators (translucent emojis show partial agreement; ⚠️ indicates conflicts).

- **State Persistence**  
  Filters, sort order, and expanded rows are preserved in the URL – you can bookmark or share a specific view.

https://github.com/user-attachments/assets/a37ee7b6-27e8-459a-a092-be67ee769b5e

https://github.com/user-attachments/assets/3a12f927-1050-485e-b6f7-5df151685a58

## Usage

0.  **Running the Application**:
    - Ensure Python 3.12+ is installed.
    - Download this repository and run `!browse_db.bat` on Windows (or the corresponding sh scripts, tested on Crostini and Ubuntu 24). A Virtual Environment with the according requirements will be automatically created if it doesn't yet exist. After startup, the application will be available at `http://127.0.0.1:5000`, and a browser window should open to this address automatically. After the .venv is created, also optionally start `!queue_manager.bat` and your vLLM endpoint (see example) to allow for paper classification/verification *(browsing an existing database doesn't require that)*.
    - Albeit untested, this should run fine in Mac, by adjusting the startup script accordingly
    - Look at the help page in the Web application itself for more instructions about the Web interface itself (Note: those instructions are currently outdated, some functionality has been changed or added).

2.  **Database Setup**:
    - You can import a BibTeX file directly from the web interface after the application is running. If no database is found on startup, the application will copy `fallback.sqlite` to the data directory to ensure it can launch for the first import or a backup restore.
### 3. LLM Integration

- Start an **OpenAI‑compatible inference server** (e.g., vLLM, llama.cpp, TabbyAPI) running a reasoning model. *vLLM is strongly recommended for high‑throughput batch processing*
- Configure the server URL in `shared/config.py` (variable `LLM_SERVER_URL`, default `http://localhost:8086`).
- In the web UI, use the **Batch Tasks** menu to trigger classification/verification:
  - **Classify / Verify** individual papers via buttons in the detail row.
  - Batch modes: `all`, `remaining`, `no_features` (papers lacking features), `on_topic_implementation`, and **Consensus** (re‑classify until verifier agrees).

### 4. Interactive Help

Click the **?** button in the top‑right corner for a detailed guide on symbols, keyboard shortcuts (F1 for help, F3 for search, Ctrl+S to save), and all UI features.

---

## Acknowledgments

Developed by [**Luis Alfredo da Silva**](https://zidrewndacht.github.io/), to assist his Master’s degree research at [**Universidade do Estado de Santa Catarina (UDESC)**](https://www.udesc.br/cct).

At least the following open‑source libraries (and their dependencies) are used:

**Backend**  
[Python](https://www.python.org/), [Flask](https://flask.palletsprojects.com/), [SQLite3](https://www.sqlite.org/), [bibtexparser](https://pypi.org/project/bibtexparser/)

**Frontend**  
[HTML5](https://developer.mozilla.org/en-US/docs/Web/Guide/HTML/HTML5), [CSS3](https://developer.mozilla.org/en-US/docs/Web/CSS), [Vanilla JS](https://developer.mozilla.org/en-US/docs/Web/JavaScript)

**Data Visualization**  
[Chart.js](https://www.chartjs.org/), [chartjs-plugin-datalabels](https://chartjs-plugin-datalabels.netlify.app/), [d3.js](https://d3js.org/), [d3-cloud.js](https://github.com/jasondavies/d3-cloud)

**PDF View/Annotation**  
[PDF.js](https://mozilla.github.io/pdf.js/getting_started/)

**Utilities**  
[rcssmin](https://opensource.perlig.de/rcssmin/), [rjsmin](https://opensource.perlig.de/rjsmin/), [openpyxl](https://openpyxl.readthedocs.io/), [pako](https://nodeca.github.io/pako/), [Zstandard](https://github.com/facebook/zstd)

<img width="1995" height="1579" alt="image" src="https://github.com/user-attachments/assets/5591360f-cec9-4b9f-b544-3a063402065f" />