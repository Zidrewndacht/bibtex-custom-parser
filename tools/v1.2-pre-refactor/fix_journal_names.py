# fix_journal_names.py
# Single-use tool (hopefully) to fix a mis-import to the DB where all journal/conference names were set as lowercase and the issue was found only after LLM classification.
# This finds the correct names in a new BibTeX file (should be equivalent to the originally imported at least as far as journals mentioned) and updates the DB replacing the lowercase entries.

import sqlite3
import bibtexparser
from bibtexparser.bparser import BibTexParser
from bibtexparser.customization import homogenize_latex_encoding
import argparse

def load_correct_names(reference_bib_file):
    """Load correct journal/conference names from reference BibTeX file"""
    # Configure BibTeX parser
    parser = BibTexParser(common_strings=True)
    parser.customization = homogenize_latex_encoding
    parser.ignore_nonstandard_types = False

    # Parse reference BibTeX file
    with open(reference_bib_file, 'r', encoding='utf-8') as f:
        bib_db = bibtexparser.load(f, parser=parser)

    # Create mapping from lowercase to correct case
    name_mapping = {}
    
    for entry in bib_db.entries:
        # Get journal or booktitle (conference name)
        journal_name = entry.get('journal', '') or entry.get('booktitle', '')
        if journal_name:
            lowercase_name = journal_name.lower()
            name_mapping[lowercase_name] = journal_name
            print(f"Added mapping: '{lowercase_name}' -> '{journal_name}'")

    return name_mapping

def fix_journal_names(db_path, reference_bib_file):
    """Fix lowercase journal names in the database using reference file"""
    # Load correct names from reference file
    name_mapping = load_correct_names(reference_bib_file)
    
    # Connect to database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get all unique journal names that are completely lowercase
    cursor.execute("SELECT DISTINCT journal FROM papers WHERE journal IS NOT NULL AND journal != ''")
    all_journals = cursor.fetchall()
    
    lowercase_journals = []
    for (journal,) in all_journals:
        if journal.islower() and journal.lower() in name_mapping:
            lowercase_journals.append(journal)
    
    print(f"Found {len(lowercase_journals)} lowercase journal names to fix")
    
    # Update the database
    updated_count = 0
    for old_journal in lowercase_journals:
        old_lowercase = old_journal.lower()
        if old_lowercase in name_mapping:
            new_journal = name_mapping[old_lowercase]
            print(f"Updating: '{old_journal}' -> '{new_journal}'")
            
            # Update all records with this journal name
            cursor.execute("UPDATE papers SET journal = ? WHERE journal = ?", (new_journal, old_journal))
            updated_count += cursor.rowcount
    
    conn.commit()
    conn.close()
    
    print(f"Updated {updated_count} records with correct journal names")

def preview_changes(db_path, reference_bib_file):
    """Preview what changes would be made without actually updating"""
    # Load correct names from reference file
    name_mapping = load_correct_names(reference_bib_file)
    
    # Connect to database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get all unique journal names that are completely lowercase
    cursor.execute("SELECT DISTINCT journal FROM papers WHERE journal IS NOT NULL AND journal != ''")
    all_journals = cursor.fetchall()
    
    lowercase_journals = []
    for (journal,) in all_journals:
        if journal.islower() and journal.lower() in name_mapping:
            lowercase_journals.append(journal)
    
    print("Preview of changes:")
    print("=" * 50)
    for old_journal in lowercase_journals:
        old_lowercase = old_journal.lower()
        if old_lowercase in name_mapping:
            new_journal = name_mapping[old_lowercase]
            print(f"'{old_journal}' -> '{new_journal}'")
    
    print(f"\nTotal records that would be updated: {len(lowercase_journals)}")
    
    conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Fix lowercase journal/conference names in database using reference BibTeX file')
    parser.add_argument('db_file', help='SQLite database file path')
    parser.add_argument('reference_bib_file', help='Reference BibTeX file with correct capitalization')
    parser.add_argument('--preview', action='store_true', help='Preview changes without applying them')
    args = parser.parse_args()
    
    if args.preview:
        preview_changes(args.db_file, args.reference_bib_file)
    else:
        fix_journal_names(args.db_file, args.reference_bib_file)