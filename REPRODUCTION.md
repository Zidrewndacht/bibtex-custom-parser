This document provides instructions for reproducing the empirical results presented in our paper. 

Because LLM inference is inherently stochastic, exact numerical replication (e.g., exactly 90.48% perfect agreement) is not expected. However, the provided artifacts, databases, and analysis scripts will allow you to verify the pipeline's mechanics, observe the same statistical distributions within the reported confidence intervals, and reproduce the exact formatting of the paper's tables.

## Artifact Inventory

This release includes the full ResearchParsa application alongside the specific artifacts used for the paper's evaluation:

*   **`/example_config/inference_engine_examples/vLLM Qwen3.6-27B-AutoRound.bat`**: The exact Docker/vLLM launch script used to serve the reasoning model.
*   **`/reproduction/100_papers_set_doi.txt`**: Almost complete list of DOIs for the 100-paper stratified subset.
*   **`/reproduction/100_papers_set_papers_missing_doi.csv`**: Metadata for papers in the 100-paper set lacking a DOI (for manual retrieval if an exact replica is needed).
*   **`/reproduction/1200_papers_set_doi.txt`**: Almost complete list of DOIs for the full 1,200-paper dataset (for large-scale testing).
*   **`/reproduction/1200_papers_set_papers_missing_doi.csv`**: Metadata for papers in the full dataset lacking a DOI.
*   **`/reproduction/build_bibtex_from_doi.py`**: Sample script to reconstruct the source BibTeX file by querying the Crossref API using the DOI lists.
*   **`/reproduction/db.human_classified_100_papers.sqlite`**: The 100-paper database with human expert annotations (used for the Human-AI Alignment study). *Note: Publisher-owned abstracts and keywords have been deliberately scrubbed from this file to comply with copyright restrictions. It serves purely as the ground-truth classification labels.*
*   **`/meta/agreement_human_cli_v1.4.py`**: Script to generate the Human-AI Alignment Summary table (Table 5 in the paper). Tables 1-4 are generated from the Web interface itself as instructed below.

*(Note: We provide DOI lists and a script to legally reconstruct the source BibTeX data via the Crossref API. The full 1,200-paper dataset DOI list is also provided for large-scale testing. You may also import your own `.bib` or `.csv` files to test the pipeline at scale; the suggested search query (Scopus format) below was used to gather most of the original BibTeX input data.)*

`TITLE-ABS-KEY(( "printed circuit*" OR "Circuit board*" OR pcb OR pcba ) AND ( inspection OR manufactur* OR assembly OR defect* OR solder* OR weld* OR "Automat* optical" )) AND PUBYEAR > 1973 AND PUBYEAR < 2027 AND ( LIMIT-TO ( DOCTYPE,"ar" ) OR LIMIT-TO ( DOCTYPE,"cp" ) OR LIMIT-TO ( DOCTYPE,"re" ) ) AND ( LIMIT-TO ( PUBSTAGE,"final" ) )  `

---

## Prerequisites

*   **OS**: Windows (Tested on Windows 11 Enterprise LTSC 26100. The provided `.bat` script assumes a Windows host with WSL2). An earlier version was tested and confirmed working on Linux (Ubuntu 24.04 LTS). It should also work, but the version provided here was only tested on Windows.
*   **Hardware**: NVIDIA GPU(s). The provided script is pre-configured for **dual RTX 3090s (48GB total VRAM)** with no display attached to the discrete GPUs (iGPU display). *See "Hardware Adaptation" below for other setups.*
*   **Software**: 
    *   Docker Desktop with WSL2 backend and NVIDIA Container Toolkit.
    *   Python (tested with 3.14).

---

## Step-by-Step Reproduction Guide

### Step 1: Launch the Inference Engine
The pipeline requires a local OpenAI-compatible inference endpoint. We used vLLM for its continuous batching and prefix-caching capabilities.

1. Ensure Docker Desktop is running.
2. Execute the provided launch script:
   ```cmd
   example_config\inference_engine_examples\vLLM Qwen3.6-27B-AutoRound.bat
   ```
3. Wait for the Docker container to download the `Lorbus/Qwen3.6-27B-int4-AutoRound` weights and initialize the vLLM server on `http://localhost:8086`.

### Step 2: Reconstruct Source Data and Start ResearchParsa
1. **Reconstruct the BibTeX data**: Rebuild the source `.bib` file using the provided DOI lists. This can be done via the Crossref API (e.g., querying `https://api.crossref.org/works/{DOI}/transform/application/x-bibtex` or using DOI content negotiation with the `Accept: application/x-bibtex` header). Combine the retrieved entries into a single BibTeX file. A small number of older or niche papers lack DOIs, refer to the `*_missing_doi.csv` files if exact dataset reproduction is desired.

2. Start the ResearchParsa Flask backend and frontend by running `!browse_db.bat`. A Virtual Environment with the required dependencies will be automatically created. The application will be available at `http://127.0.0.1:5001` by default. To enable AI classification, start `!queue_manager.bat` (wait until `!browse_db.bat` has finished downloading and initializing the virtual environment).

3. In the ResearchParsa web UI, **Import the BibTeX**: Use the "Import BibTeX / CSV" button to load the `reproduction\reconstructed_100.bib` file you just generated. This will populate the system with the exact 100 papers used in the paper's stratified validation subset, complete with their abstracts. Ensure your `domain_config.yaml` is configured for the PCB AOI taxonomy.

### Step 3: Run the Classification
1. In the ResearchParsa UI, trigger the **Automated Classify Until Consensus** inside Batch Tools.
2. The system will automatically execute the triple-run consensus architecture.
3. Wait for the queue manager to process all papers and reach consensus. *(On dual RTX 3090s with the selected model, this takes approximately 60 minutes for 100 papers).*

### Step 4: Generate the Statistical Tables
Once the classification is complete, you can generate the LaTeX tables presented in the paper using the provided Python scripts.

#### Tables 1–4 and consensus chart (except Power): 3-Run Agreement Analysis

To analyze the internal consistency of the AI runs (Perfect, Uncertain, Contradiction), open the "3-run Agreement Report" in the Batch Tools **after** finishing inference. 
The LaTeX tables themselves can be exported via the "Copy LaTeX" button.

#### Table 5: Human-AI Alignment Summary

This requires the separate human-annotated database and a standalone script, which compares the generated AI classifications against the human-annotated database.

```batch
python meta/agreement_human_cli_v1.4.py ^
  --user-db reproduction/db.human_classified_100_papers.sqlite ^
  --ai-db <path_to_your_live_researchparsa_db.sqlite> ^
  --config domain_config.yaml ^
  -o output_tables/human_ai_alignment_table.tex
```
*This will save the LaTeX code for Table 5, along with a console summary showing Exact Match, AI Overconfidence, and Conflict rates.*

---

## Expected Results & Stochasticity

Because the system relies on non-deterministic LLM sampling (which is required for high-quality reasoning traces), **your exact percentages will differ slightly from the paper**. 
You should expect the core metrics (e.g., Perfect Agreement, Contradiction rate) to fall within the **95% Wilson Score Confidence Intervals** reported in the paper. 

---

## Hardware Adaptation (Non-Dual 3090 Setups)

The provided `.bat` script is optimized for **48GB of VRAM across two NVIDIA RTX 3090 GPUs** (`--tensor-parallel-size 2`, `--kv-cache-memory=12325992448`). 

If you are reproducing this on different hardware (e.g., a single GPU, or a GPU with less VRAM), **you must modify the `.bat` file**, otherwise the container will crash with Out-Of-Memory (OOM) errors.

**Adjustments for Single GPU / Lower VRAM:**
1. Change `--tensor-parallel-size 2` to `--tensor-parallel-size 1`.
2. Remove, lower `--kv-cache-memory` or replace it with `--gpu-memory-utilization 0.90` (with a value that fits your environment).
3. *Warning*: Throughput and energy efficiency will scale non-linearly. The superlinear scaling reported in the paper (Table 6) is a direct result of the batch-size ceiling imposed by VRAM; a single 24GB GPU will be significantly slower and less energy-efficient per paper.

**Display Attachment Warning:**
As noted in the paper, attaching a monitor directly to the discrete GPUs running vLLM under WSL2 causes severe performance degradation due to host/VM context switching. Ensure your displays are connected to the motherboard (iGPU) or run the machine headless.
```