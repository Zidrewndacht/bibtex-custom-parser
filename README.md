## bibtex-custom-parser
LLM-based analysis of abstracts from a BibTeX file. Tailor-made for PCB inspection papers, but may be used for other purposes with (fairly substantial) adaptation.

This was made to help research on PCB inspection. It allows for searching, filtering, statistics and, mainly, automatic, traceable classification and verification through natural language processing using large language models.

This is not yet fully-featured. For example, BibTeX import from the Web UI isn't implemented yet. See TODO.txt for more information. 

A read-only version for demonstration purposes can be accessed via GitHub Pages [here](https://zidrewndacht.github.io/bibtex-custom-parser). The static demo has full client-side browsing/sarching/filtering/stats functionality. It may not be updated as frequently as the actual code.

# Usage:

Install Python 3.x.
Create a venv and prepare it with requirements.txt.
Configure environment variables on `globals.py` as needed.
Set up llama-server or another OpenAI-compatible server with deepseek-style `<think>` reasoning support.
Run `browse_db.py`. This file calls the other scripts when needed.
