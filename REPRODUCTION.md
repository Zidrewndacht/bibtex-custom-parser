This document provides instructions for reproducing the empirical results presented in our paper. 

Because LLM inference is inherently stochastic, exact numerical replication (e.g., exactly 90.48% perfect agreement) is not expected. However, the provided artifacts, databases, and analysis scripts will allow you to verify the pipeline's mechanics, observe the same statistical distributions within the reported confidence intervals, and reproduce the exact formatting of the paper's tables.

## Artifact Inventory

This release includes the full ResearchParsa application alongside the specific artifacts used for the paper's evaluation:

*   **`/example_config/inference_engine_examples/vLLM Qwen3.6-27B-AutoRound.bat`**: The exact Docker/vLLM launch script used to serve the reasoning model.
*   **`/reproduction/unclassified_100_papers_backup.parça.zst`**: A backup of the stratified, unclassified 100-paper subset, ready to be imported and classified.
*   **`/reproduction/db.human_classified_100_papers.sqlite`**: The same 100 papers with human expert annotations (used for the Human-AI Alignment study).
*   **`/reproduction/ai_classified_papers_backup.parça.zst`**: A backup of the already classified 100-paper subset for convenience (if you can't run inference yourself).
*   **`/meta/agreement_human_cli_v1.4.py`**: Script to generate the Human-AI Alignment Summary table (Table 5 in the paper). Tables 1-4 are generated from the Web interface itself as instructed below.

*(Note: The full 1,200-paper dataset is not included due to possible redistribution restrictions from Scopus/IEEE/ACM. However, the 100-paper stratified subset is sufficient to reproduce the Human-AI alignment table and verify the consensus mechanics. You may also import your own `.bib` or `.csv` files to test the pipeline at scale. PDF files the frontend may say are available also are excluded from the provided backups, so the Annotator module won't open them -- this is not related to the scope of this study)*

---

## Prerequisites

*   **OS**: Windows (Tested on Windows 11 LTSC 26100. The provided `.bat` script assumes a Windows host with WSL2).
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

### Step 2: Start ResearchParsa and Import Data
1. Start the ResearchParsa Flask backend and frontend by running `!browse_db.bat`. A Virtual Environment with the required dependencies will be automatically created. The application will be available at `http://127.0.0.1:5001` by default. To enable AI classification, start `!queue_manager.bat` (after !browse_db.bat has finished downloading the venv).

2. In the ResearchParsa web UI, **Restore the Database**: Instead of importing a `.bib` file, use the "Restore Backup" in "Export & Backup" to load `data/reproduction/unclassified_100_papers.parça.zst`. This will populate the system with the exact 100 papers used in the paper's stratified validation subset as well as the corresponding `domain_config.yaml` (PCB AOI taxonomy) and configurable prompts.

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

This requires the separate human-annotated database database and a standalone script, which script compares the generated AI classifications against the human-annotated database.

```batch
python meta/agreement_human_cli_v1.4.py ^
  --user-db data/reproduction/human_classified_100_papers.db ^
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
3. Remove, lower `--kv-cache-memory` or replace it with `--gpu-memory-utilization 0.90` (with a value that fits your environment).
4. *Warning*: Throughput and energy efficiency will scale non-linearly. The superlinear scaling reported in the paper (Table 6) is a direct result of the batch-size ceiling imposed by VRAM; a single 24GB GPU will be significantly slower and less energy-efficient per paper.

**Display Attachment Warning:**
As noted in the paper, attaching a monitor directly to the discrete GPUs running vLLM under WSL2 causes severe performance degradation due to host/VM context switching. Ensure your displays are connected to the motherboard (iGPU) or run the machine headless.