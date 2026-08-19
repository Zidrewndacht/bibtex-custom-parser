# ResearchParsa

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21816041.svg)](https://doi.org/10.5281/zenodo.21816041)

Live Demo (read-only HTML export): [ResearchParsa](https://zidrewndacht.github.io/ResearchParsa).  

*The frontend was mostly tested with Mozilla Firefox and works well. The HTML export had known performance issues in Chromium‑based browsers in 2025 and wasn't extensively performance-tested since. If the page lags or stops responding on reasonably modern hardware, please use Firefox instead.*

ResearchParsa is a domain-agnostic tool for managing, classifying, and analyzing bibliographic databases of academic papers. It imports BibTeX/CSV files into an SQLite database and provides a rich, dynamically generated web interface for browsing, filtering, editing, and performing **LLM‑driven classification and verification**.

By defining your domain's taxonomy, filters, and prompt templates in a YAML configuration file, the system adapts its data model, UI columns, and statistical dashboards to any specific research field. It is designed to streamline systematic literature reviews by offering advanced search, traceable AI‑enriched metadata, and automated LaTeX table generation.

*Note: [ResearchParsa-Lite](https://github.com/Zidrewndacht/ResearchParsa-lite), minimal, generic PDF organizer/annotator is now deprecated as full ResearchParsa is now fit for any generic research domain.*

## Features

- **Domain-Agnostic Configuration**  
  Define your research domain's taxonomy, custom fields, filter types (tri-state, inclusion), and LLM prompt templates via `domain_config.yaml`. The UI, database JSON blobs, and statistics engine adapt dynamically to your schema.

- **LLM‑Powered Classification & Verification**  
  A separate **queue manager** (`queue_manager.py`) coordinates communication with an **OpenAI‑compatible LLM server** (mostly tested with vLLM, which allows for high concurrency which the task is exceedingly friendly for).  
  - Each paper is classified **three times independently** to calculate certainty and detect conflicts.  
  - A **verifier** LLM scores the classification accuracy and provides reasoning traces.  
  - An advanced **“Consensus” mode** iteratively re-classifies disputed papers until the verifier agrees or a limit is reached.  

- **Traceability & History**  
  Every AI classification, verification, and user edit is strictly logged. The “History” view provides per-set and averaged logs, LLM reasoning traces, change highlighting, and certainty indicators (translucent emojis for partial agreement; ⚠️ for conflicts).

- **Advanced Filtering & Search**  
  Server-side filters (year, page count) and dynamic client-side filtering based on your domain's configuration. The global search bar indexes all metadata, abstracts, keywords, and user comments.

- **Statistics & LaTeX Export**  
  A dedicated “Statistics” modal presents dynamic charts and lists based on the **currently visible** papers. Includes one-click generation of LaTeX `\tabularx` and `\longtable` code for journals, authors, and custom metrics, ready to paste into your manuscript.

- **PDF Management & Annotation**  
  Upload, store, and view PDFs. An integrated **PDF.js** annotator lets you highlight and add notes, which are **auto‑saved** to the server. Includes automated paywall tracking based on user comments.

- **Data Export & Archiving**  
  - **Static HTML Export**: A self-contained, compressed HTML file with full offline filtering, sorting, and charting capabilities – ideal for sharing or archiving.  
  - **XLSX Export**: Formatted Excel spreadsheets with conditional formatting and multi-sheet audit logs.
  - **Backup & Restore**: Complete Zstandard-compressed archives (`.parsa.tzst`) containing the database and all original/annotated PDFs.

- **Interactive Web Interface**  
  A Flask-based application with an interactive table. Click status symbols to cycle values, edit text fields in expanded detail rows, and preserve your exact filter/sort state in the URL for bookmarking.

(videos below are outdated as they represent an older version that lacked history and multi-set classification, among other features. But it provides a quick introduction to the overall user interface)

https://github.com/user-attachments/assets/a37ee7b6-27e8-459a-a092-be67ee769b5e

https://github.com/user-attachments/assets/3a12f927-1050-485e-b6f7-5df151685a58

## Usage

1.  **Running the Application**:
    - Ensure Python 3.12+ is installed.
    - Download this repository and run `!browse_db.bat` on Windows (or the corresponding `.sh` scripts on Linux/macOS). A Virtual Environment with the required dependencies will be automatically created.
    - The application will be available at `http://127.0.0.1:5001` (or your configured port).
    - To enable AI classification, start `!queue_manager.bat` and your OpenAI-compatible LLM endpoint (tested with local vLLM, may run as well with cloud-based APIs to reasoning models, still untested). Browsing and editing an existing database does not require the queue manager.

2.  **Domain & Database Setup**:
    - Configure your domain taxonomy, UI theme, and LLM prompts in `domain_config.yaml`, and general settings in `config.yaml`.
    - Import a BibTeX (`.bib`) or IEEE Xplore CSV file directly from the web interface. If no database exists, the app initializes a fresh schema.

3.  **LLM Integration**:
    - Start an **OpenAI‑compatible inference server** (vLLM is strongly recommended for high‑throughput batch processing).
    - Configure the server URL and API keys in `config.yaml`.
    - Use the **Batch Tasks** menu in the web UI to trigger classifications, verifications, or consensus runs across your dataset.

4.  **Interactive Help**:
    - Click the **?** button in the top‑right corner for a detailed guide on symbols, keyboard shortcuts (F1 for help, F3 for search, Ctrl+S to save), and UI features.

---


## Licensing
This project uses a modular licensing approach to balance open scientific research with the protection of our product development efforts:

*   **Core Backend & Scientific Artifacts:** The backend pipeline, queue manager, analysis scripts, and reproduction data (everything outside the `/web` directory) are licensed under the **Apache License 2.0**. You are free to use, modify, and distribute these components for any purpose, including commercial applications.
*   **Web UI:** The web interface and user experience components located in the `/web` directory are licensed under the **PolyForm Noncommercial License 1.0.0**. You may use, modify, and run the frontend for non-commercial purposes (including academic research, peer review, and personal use). Commercial use of the frontend requires a separate licensing agreement with the authors.

## Third-Party Software and Licenses

This project bundles several third-party open-source libraries. While the core ResearchParsa application is licensed as described above, these bundled libraries retain their original licenses:

*   **PDF.js** (`web/static/pdfjs/`): Licensed under the Apache License 2.0 (Mozilla Foundation). Our custom autosave integration (`autosave.js`) is also released under Apache 2.0 to maintain compatibility.
*   **Chart.js, D3.js, Pako, etc.** (`web/static/libs/`): Licensed under their respective MIT/ISC licenses.
*   **Inter Tight & Twemoji Mozilla Fonts** (`web/static/css/fonts/`): Licensed under the SIL Open Font License and CC-BY 4.0, respectively.

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