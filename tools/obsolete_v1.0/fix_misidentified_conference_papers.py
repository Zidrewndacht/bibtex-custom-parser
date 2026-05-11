#!/usr/bin/env python3
# fix_paper_types_simple.py
# Simple script to fix paper types - direct approach

import sqlite3
import bibtexparser
from bibtexparser.bparser import BibTexParser
from bibtexparser.customization import homogenize_latex_encoding
import argparse
import re

def load_corrected_bibtex_titles(bibtex_path):
    """Load titles from corrected BibTeX file"""
    with open(bibtex_path, 'r', encoding='utf-8') as f:
        bibtex_str = f.read()
    
    parser = BibTexParser()
    parser.customization = homogenize_latex_encoding
    bib_database = bibtexparser.loads(bibtex_str, parser=parser)
    
    # Create a mapping from cleaned title to entry type
    title_to_type = {}
    for entry in bib_database.entries:
        title = entry.get('title', '')
        # Clean title: remove LaTeX formatting like { }, but preserve content
        cleaned_title = re.sub(r'[{}]', '', title).strip()
        normalized_title = re.sub(r'\s+', ' ', cleaned_title.lower())
        entry_type = entry.get('ENTRYTYPE', '').lower()
        title_to_type[normalized_title] = entry_type
    
    return title_to_type

def normalize_title(title):
    """Normalize title for comparison"""
    if not title:
        return ''
    # Remove LaTeX formatting and normalize
    cleaned_title = re.sub(r'[{}]', '', title).strip()
    return re.sub(r'\s+', ' ', cleaned_title.lower())

def fix_paper_types(db_path, corrected_bibtex_path):
    """Fix paper types from journal to conference based on corrected BibTeX"""
    print(f"Loading corrected data from {corrected_bibtex_path}...")
    corrected_data = load_corrected_bibtex_titles(corrected_bibtex_path)
    
    print(f"Connecting to database {db_path}...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get all papers that are currently marked as 'article' (journal papers)
    cursor.execute("SELECT id, title, type FROM papers WHERE type = 'article'")
    journal_papers = cursor.fetchall()
    
    print(f"Found {len(journal_papers)} journal papers in database")
    print(f"Found {len(corrected_data)} entries in corrected BibTeX")
    
    fixed_count = 0
    for paper_id, db_title, current_type in journal_papers:
        db_normalized = normalize_title(db_title)
        
        if db_normalized in corrected_data:
            corrected_type = corrected_data[db_normalized]
            
            if corrected_type == 'inproceedings':
                print(f"Changing '{db_title[:50]}...' from {current_type} to {corrected_type}")
                
                # Update the paper type while preserving all other fields
                cursor.execute("""
                    UPDATE papers 
                    SET type = 'inproceedings'
                    WHERE id = ?
                """, (paper_id,))
                fixed_count += 1
    
    conn.commit()
    conn.close()
    
    print(f"\nFixed {fixed_count} papers from journal to conference papers")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Simple fix for paper types')
    parser.add_argument('db_file', help='SQLite database file path')
    parser.add_argument('corrected_bibtex', help='Corrected BibTeX file path')
    
    args = parser.parse_args()
    
    fix_paper_types(args.db_file, args.corrected_bibtex)