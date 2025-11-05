# ResearchParça

Live Demo (read-only HTML export): [ResearchParça](https://zidrewndacht.github.io/bibtex-custom-parser).

**Also check ResearchParça Lite (Minimal, generic PDF organizer/annotator):** [ResearchParça-Lite](https://github.com/Zidrewndacht/ResearchParsa-lite)

The frontend was mostly tested with Mozilla Firefox and works well. The HTML export has some **known performance issues in Chromium-based browsers**. If the page lags, stops responding, etc, in reasonably modern hardware, please run it in Firefox instead.

--

ResearchParça is a tool for managing and analyzing a bibliographic database, specifically tailored for academic papers on Printed Circuit Board (PCB) inspection. It processes BibTeX files, stores the data in an SQLite database, and provides a web interface for browsing, filtering, and editing the information. The core functionality includes using Large Language Models (LLMs) to automatically classify papers based on their content (title, abstract, keywords) and to verify these classifications.

The system is designed to streamline literature reviews by allowing for advanced search capabilities, statistical analysis of the dataset, and traceable, LLM-driven data enrichment.

## Features

- **BibTeX Import**: Imports bibliographic data from `.bib` files into a structured SQLite database. The import process handles duplicate entries by checking for existing DOIs or matching titles and years. A tool to convert IEEE Xplore CSVs is included in `/tools`, but automatic CSV import isn't yet implemented.

- **Web Interface**: A Flask-based web application (`browse_db.py`) provides a user-friendly interface to view, filter, and edit the paper database. The server starts up and automatically opens the interface in a web browser.

- **LLM-Powered Classification (Optimized for Batching)**: The `automate_classification.py` script sends paper metadata to a local **OpenAI-compatible LLM server, supporting vLLM, TabbyAPI, and llama.cpp** to classify papers based on a detailed prompt template.
    *   Classification results, **including the model's reasoning trace**, are saved to the database.
    *   Optimized for **high concurrency** (defaults to up to 480 parallel requests) to utilize high-throughput engines like vLLM. This optimization reduced the full classification + verification time for approximately 14,000 papers from about 6 days to **around 8 hours** on testing hardware.
    *   Includes an advanced **'Re-classify Until Consensus' agentic mode**. This iteratively re-classifies misclassified papers until verification consensus is reached. Note that this is still imperfect, as if classifier and verifier end up reaching consensus in an incorrect classification, it'll still go unnoticed.
    *   Sample code for LLM engine startup is included at `/inference_engine_examples`.

- **LLM-Powered Verification**: `verify_classification.py` uses the LLM to review and verify the accuracy of a previous classification, providing a score and a "verified" status. This process also runs in different modes ('all', 'remaining', 'id').

- **Advanced Filtering and Search**: The web UI allows for server-side filtering by year range, minimum page count, and off-topic Every other filtering functionality, including search, is done purely client-side.

- **Comprehensive Statistical Analysis and Visualization**: The web UI includes extensive client-side tools to view statistics and charts based on the **currently visible filtered data**. This includes a dedicated "View Statistics" modal presenting:
    *   Lists of repeating entities such as **Journals, Conferences, Keywords, Authors, Research Areas**, and mentioned **Models**. Users can click items in these lists to instantly search the database for that term.
    *   A dynamic **Keyword Cloud** view.
    *   Distribution charts for **Publication Types**, **Survey vs Primary Papers**, **Techniques**, and **Features**. These can be viewed in various formats, including **Cumulative** and **Stacked**.
    *   Histograms showing the distribution of **Relevance Scores** and **Verifier Scores**.
    *   Metrics covering **Dataset Scope** (on-topic vs. off-topic), **SMT vs THT** papers, and counts of documents with PDFs or annotations.

- **Conference Deannualization**: This is still half-implemented. `/tools/deannualize_conferences` and `/tools/post_process_conferences` scripts generate a deannualized_conference field in the DB, which is be used by the Web frontend for better "repeating conferences" statistics. The parsing isn't perfect, and doesn't happen automatically on import yet.

- **Data Editing**: Users can directly edit classification fields, add comments (`user_trace`), and manage metadata through the web interface.

- **PDF Management**: The application supports uploading, storing, and viewing PDF versions of papers It includes an integrated, branded version of PDF.js that allows for annotating documents directly in the browser, with changes being automatically saved to the server

- **Data Export**: The currently filtered view of the database can be exported to:
    *   A self-contained, interactive static **HTML file**. This export is compressed for a smaller file size and includes client-side filtering and charting capabilities
    *   An **Excel (.xlsx) file**, with boolean fields conditionally formatted for readability, ready to be processed using pivot tables and/or any other Excel tools

- **Backup and Restore**: The system includes functionality to create a complete backup (`.parça.zst` file) containing the SQLite database, all stored PDFs (original and annotated), and an HTML/XLSX export

https://github.com/user-attachments/assets/a37ee7b6-27e8-459a-a092-be67ee769b5e

https://github.com/user-attachments/assets/3a12f927-1050-485e-b6f7-5df151685a58

## Usage

0.  **Running the Application**:
    - Ensure Python 3.x is installed.
    - Download this repository and run !browse_db.bat. A Virtual Environment with the according requirements will be automatically created if it doesn't yet exist. After startup, the application will be available at `http://127.0.0.1:5000`, and a browser window should open to this address automatically.
    - Albeit untested, this should run fine in Linux or Mac, you just have to manually create and run the venv in that case.
    - Look at the help page in the Web application itself for more instructions about the Web interface itself (Note: those instructions are currently outdated, some functionality has been changed or added).

2.  **Database Setup**:
    - You can import a BibTeX file directly from the web interface after the application is running. If no database is found on startup, the application will copy `fallback.sqlite` to the data directory to ensure it can launch for the first import or a backup restore.
      
3.  **LLM Integration**:
    - Start an OpenAI-compatible inference server (e.g., vLLM or llama.cpp). 
    - From the web UI, you can trigger classification and verification tasks for individual papers or in batches ('all' or 'remaining').
    - Alternatively, manually run classification using `automate_classification.py` and `verify_classification.py`. Manual run supports (not yet properly documented) additional operating modes, check the script's usage hints.

    
    - Start an OpenAI-compatible inference server. If the hardware allows, **vLLM is highly recommended for high-speed batch processing** due to its optimization for heavy continuous batching, tested to be **15 times** faster than llama.cpp for this application in the developer's hardware.
    - `/inference_engine_examples` folder has sample settings for multiple supported inference engines. Those are tailored for a specific environment (2x RTX 3090 on a Windows workstation) and should be taken as reference only.
    - From the web UI, you can trigger classification and verification tasks for individual papers or in batches ('all', 'remaining', 'no_features', 'on_topic\_implementation', or the advanced **'Consensus'** mode).
    - Alternatively, manually run classification using `automate_classification.py` and `verify_classification.py`. Manual run supports additional operating modes, check the script's usage hints.

## Acknowledgments

Developed by [**Luis Alfredo da Silva**](https://zidrewndacht.github.io/), to assist his own Master's degree research at [**Universidade do Estado de Santa Catarina (UDESC)**](https://www.udesc.br/cct).

At least the following open source libraries, and its dependencies, are leveraged by this software:

**Backend:**
[Python](https://www.python.org/),
[Flask](https://flask.palletsprojects.com/),
[SQLite3](https://www.sqlite.org/)
[bibtexparser](https://pypi.org/project/bibtexparser/)

**Frontend:**
[HTML5](https://developer.mozilla.org/en-US/docs/Web/Guide/HTML/HTML5),
[CSS3](https://developer.mozilla.org/en-US/docs/Web/CSS),
[Vanilla JS](https://developer.mozilla.org/en-US/docs/Web/JavaScript)

**Data Visualization:**
[Chart.js](https://www.chartjs.org/),
[chartjs-plugin-datalabels](https://chartjs-plugin-datalabels.netlify.app/), 
[d3.js](https://d3js.org/),
[d3-cloud.js](https://github.com/jasondavies/d3-cloud) 

**PDF View/Annotation/Autosave:**
[PDF.js](https://mozilla.github.io/pdf.js/getting_started/)

**Utilities:**
[rcssmin](https://opensource.perlig.de/rcssmin/) (minification),
[rjsmin](https://opensource.perlig.de/rjsmin/) (minification),
[openpyxl](https://openpyxl.readthedocs.io/) (Excel export),
[pako](https://nodeca.github.io/pako/) (compressed HTML export),
[Zstandard](https://github.com/facebook/zstd) (backup/restore).
<img width="1995" height="1579" alt="image" src="https://github.com/user-attachments/assets/5591360f-cec9-4b9f-b544-3a063402065f" />