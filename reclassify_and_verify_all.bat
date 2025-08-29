@echo off
echo Are you sure you want to re-classify ALL papers?
pause
D:\!staging\BibTeX-custom-parser\.venv\Scripts\python D:\!staging\BibTeX-custom-parser\automate_classification.py --mode all
D:\!staging\BibTeX-custom-parser\.venv\Scripts\python D:\!staging\BibTeX-custom-parser\verify_classification.py --mode all
pause