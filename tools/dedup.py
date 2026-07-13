# cleanup_duplicates.py
# Removes duplicates that got through due to previous issues in import code.
import sqlite3
import re
import argparse

def normalize_title_for_comparison(title):
    """Normalize title for duplicate detection by removing case, extra whitespace, and common variations."""
    if not title:
        return ""
    
    # Convert to lowercase
    normalized = title.lower()
    
    # Remove extra whitespace and normalize spaces
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    
    # Remove common punctuation variations that don't change meaning
    # Replace various dash types with standard space
    normalized = re.sub(r'[-–—]', ' ', normalized)
    
    # Remove extra spaces created by dash replacement
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    
    # Remove common leading/trailing punctuation
    normalized = normalized.strip(' .,;:')
    
    return normalized

def calculate_completeness_score(row):
    """Calculate a score based on how much information is filled in."""
    score = 0
    
    # Count non-empty fields that indicate completeness
    if row['abstract']: score += 10  # Abstract is valuable
    if row['authors']: score += 5   # Authors are important
    if row['doi']: score += 8       # DOI is important for identification
    if row['keywords']: score += 3  # Keywords add value
    if row['journal']: score += 4   # Journal/conference info
    if row['volume']: score += 2    # Volume info
    if row['pages']: score += 2     # Pages info
    if row['issn']: score += 3      # ISSN is valuable
    
    # Classification fields
    if row['research_area']: score += 2
    if row['is_offtopic'] is not None: score += 2
    if row['relevance'] is not None: score += 2
    if row['is_survey'] is not None: score += 2
    if row['is_through_hole'] is not None: score += 2
    if row['is_smt'] is not None: score += 2
    if row['is_x_ray'] is not None: score += 2
    
    # Audit fields
    if row['verified'] is not None: score += 1
    if row['verified_by']: score += 1
    if row['changed']: score += 1
    if row['changed_by']: score += 1
    
    return score

def get_paper_data(cursor, paper_id):
    """Get all data for a paper as a dictionary."""
    cursor.execute("""
        SELECT id, type, title, authors, year, month, journal, volume, pages, 
               page_count, doi, issn, abstract, keywords, research_area, 
               is_offtopic, relevance, is_survey, is_through_hole, is_smt, 
               is_x_ray, features, technique, changed, changed_by, verified, 
               estimated_score, verified_by, reasoning_trace, verifier_trace, 
               user_trace, pdf_filename, pdf_state, deannualized_conference
        FROM papers WHERE id = ?
    """, (paper_id,))
    
    row = cursor.fetchone()
    if not row:
        return None
    
    # Create a dictionary with field names
    field_names = [
        'id', 'type', 'title', 'authors', 'year', 'month', 'journal', 'volume', 'pages',
        'page_count', 'doi', 'issn', 'abstract', 'keywords', 'research_area',
        'is_offtopic', 'relevance', 'is_survey', 'is_through_hole', 'is_smt',
        'is_x_ray', 'features', 'technique', 'changed', 'changed_by', 'verified',
        'estimated_score', 'verified_by', 'reasoning_trace', 'verifier_trace',
        'user_trace', 'pdf_filename', 'pdf_state', 'deannualized_conference'
    ]
    
    return dict(zip(field_names, row))

def find_and_remove_duplicates(db_path):
    """Find and remove duplicate entries, keeping the one with more information."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    total_removed = 0
    
    # First, find all entries grouped by DOI (non-empty DOIs)
    cursor.execute("""
        SELECT doi, COUNT(*) as count 
        FROM papers 
        WHERE doi IS NOT NULL AND doi != ''
        GROUP BY doi
        HAVING COUNT(*) > 1
    """)
    doi_duplicates = cursor.fetchall()
    
    print(f"Found {len(doi_duplicates)} DOI-based duplicate groups")
    
    # Remove duplicates based on DOI - keep the one with most information
    for doi, count in doi_duplicates:
        cursor.execute("""
            SELECT id FROM papers 
            WHERE doi = ? 
        """, (doi,))
        duplicate_ids = [row[0] for row in cursor.fetchall()]
        
        # Get all duplicate records and calculate their completeness scores
        duplicate_records = []
        for dup_id in duplicate_ids:
            data = get_paper_data(cursor, dup_id)
            if data:
                score = calculate_completeness_score(data)
                duplicate_records.append((dup_id, score, data))
        
        if duplicate_records:
            # Sort by completeness score (descending), keep the highest
            duplicate_records.sort(key=lambda x: x[1], reverse=True)
            best_record_id = duplicate_records[0][0]
            ids_to_delete = [rec[0] for rec in duplicate_records[1:]]
            
            if ids_to_delete:
                placeholders = ','.join(['?' for _ in ids_to_delete])
                cursor.execute(f"DELETE FROM papers WHERE id IN ({placeholders})", ids_to_delete)
                print(f"Removed {len(ids_to_delete)} duplicate entries with DOI '{doi}' (kept '{best_record_id}' with score {duplicate_records[0][1]})")
                total_removed += len(ids_to_delete)
    
    # Now find entries grouped by normalized title + year (with one-off tolerance)
    cursor.execute("""
        SELECT title, year, COUNT(*) as count 
        FROM papers 
        WHERE title IS NOT NULL AND title != '' AND year IS NOT NULL
        GROUP BY LOWER(title), year
        HAVING COUNT(*) > 1
    """)
    exact_title_year_duplicates = cursor.fetchall()
    
    print(f"Found {len(exact_title_year_duplicates)} exact title+year duplicate groups")
    
    # Handle exact title+year matches
    for title, year, count in exact_title_year_duplicates:
        normalized_title = normalize_title_for_comparison(title)
        
        cursor.execute("""
            SELECT id FROM papers 
            WHERE LOWER(title) = ? AND year = ?
        """, (normalized_title, year))
        duplicate_ids = [row[0] for row in cursor.fetchall()]
        
        # Get all duplicate records and calculate their completeness scores
        duplicate_records = []
        for dup_id in duplicate_ids:
            data = get_paper_data(cursor, dup_id)
            if data:
                score = calculate_completeness_score(data)
                duplicate_records.append((dup_id, score, data))
        
        if duplicate_records:
            # Sort by completeness score (descending), keep the highest
            duplicate_records.sort(key=lambda x: x[1], reverse=True)
            best_record_id = duplicate_records[0][0]
            ids_to_delete = [rec[0] for rec in duplicate_records[1:]]
            
            if ids_to_delete:
                placeholders = ','.join(['?' for _ in ids_to_delete])
                cursor.execute(f"DELETE FROM papers WHERE id IN ({placeholders})", ids_to_delete)
                print(f"Removed {len(ids_to_delete)} duplicate entries with title '{duplicate_records[0][2]['title']}' and year '{year}' (kept '{best_record_id}' with score {duplicate_records[0][1]})")
                total_removed += len(ids_to_delete)
    
    # Now find entries with one-off year differences (year ± 1) and same normalized title
    # Get all papers and group by normalized title
    cursor.execute("""
        SELECT id, title, year FROM papers 
        WHERE title IS NOT NULL AND title != '' AND year IS NOT NULL
        ORDER BY LOWER(title), year
    """)
    all_papers = cursor.fetchall()
    
    # Group papers by normalized title
    title_groups = {}
    for paper_id, title, year in all_papers:
        normalized = normalize_title_for_comparison(title)
        if normalized not in title_groups:
            title_groups[normalized] = []
        title_groups[normalized].append((paper_id, year))
    
    # Find potential one-off year duplicates within each title group
    one_off_duplicates = []
    for normalized_title, paper_list in title_groups.items():
        # Sort by year
        paper_list.sort(key=lambda x: x[1])
        
        # Check adjacent years for potential duplicates
        i = 0
        while i < len(paper_list) - 1:
            current_id, current_year = paper_list[i]
            next_id, next_year = paper_list[i + 1]
            
            if abs(current_year - next_year) == 1:
                # Found a one-off year pair with same normalized title
                one_off_duplicates.append([current_id, next_id])
                i += 2  # Skip next since we've processed it
            else:
                i += 1
    
    print(f"Found {len(one_off_duplicates)} potential one-off year duplicate groups")
    
    # Process one-off year duplicates
    for dup_group in one_off_duplicates:
        # Get all duplicate records and calculate their completeness scores
        duplicate_records = []
        for dup_id in dup_group:
            data = get_paper_data(cursor, dup_id)
            if data:
                score = calculate_completeness_score(data)
                duplicate_records.append((dup_id, score, data))
        
        if len(duplicate_records) > 1:
            # Sort by completeness score (descending), keep the highest
            duplicate_records.sort(key=lambda x: x[1], reverse=True)
            best_record_id = duplicate_records[0][0]
            ids_to_delete = [rec[0] for rec in duplicate_records[1:]]
            
            if ids_to_delete:
                placeholders = ','.join(['?' for _ in ids_to_delete])
                cursor.execute(f"DELETE FROM papers WHERE id IN ({placeholders})", ids_to_delete)
                print(f"Removed {len(ids_to_delete)} one-off year duplicate entries (kept '{best_record_id}' with score {duplicate_records[0][1]})")
                total_removed += len(ids_to_delete)
    
    # Also find entries with exact title matches (case-insensitive) when year is missing
    cursor.execute("""
        SELECT title, COUNT(*) as count 
        FROM papers 
        WHERE title IS NOT NULL AND title != '' AND year IS NULL
        GROUP BY LOWER(title)
        HAVING COUNT(*) > 1
    """)
    exact_title_duplicates = cursor.fetchall()
    
    print(f"Found {len(exact_title_duplicates)} exact title duplicate groups (no year)")
    
    for title, count in exact_title_duplicates:
        cursor.execute("""
            SELECT id FROM papers 
            WHERE LOWER(title) = LOWER(?)
        """, (title,))
        duplicate_ids = [row[0] for row in cursor.fetchall()]
        
        # Get all duplicate records and calculate their completeness scores
        duplicate_records = []
        for dup_id in duplicate_ids:
            data = get_paper_data(cursor, dup_id)
            if data:
                score = calculate_completeness_score(data)
                duplicate_records.append((dup_id, score, data))
        
        if len(duplicate_records) > 1:
            # Sort by completeness score (descending), keep the highest
            duplicate_records.sort(key=lambda x: x[1], reverse=True)
            best_record_id = duplicate_records[0][0]
            ids_to_delete = [rec[0] for rec in duplicate_records[1:]]
            
            if ids_to_delete:
                placeholders = ','.join(['?' for _ in ids_to_delete])
                cursor.execute(f"DELETE FROM papers WHERE id IN ({placeholders})", ids_to_delete)
                print(f"Removed {len(ids_to_delete)} duplicate entries with title '{duplicate_records[0][2]['title']}' (no year) (kept '{best_record_id}' with score {duplicate_records[0][1]})")
                total_removed += len(ids_to_delete)
    
    conn.commit()
    
    # Get final count
    cursor.execute("SELECT COUNT(*) FROM papers")
    final_count = cursor.fetchone()[0]
    print(f"\nCleanup completed. Removed {total_removed} duplicate entries.")
    print(f"Final database contains {final_count} unique entries.")
    
    conn.close()

def preview_duplicates(db_path):
    """Preview duplicates without deleting them."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("=== Preview of potential duplicates ===")
    
    # Check DOI duplicates
    cursor.execute("""
        SELECT doi, COUNT(*) as count, GROUP_CONCAT(title, ' | ') as titles, GROUP_CONCAT(id, ', ') as ids
        FROM papers 
        WHERE doi IS NOT NULL AND doi != ''
        GROUP BY doi
        HAVING COUNT(*) > 1
    """)
    doi_duplicates = cursor.fetchall()
    
    if doi_duplicates:
        print(f"\nDOI-based duplicates found: {len(doi_duplicates)} groups")
        for doi, count, titles, ids in doi_duplicates:
            print(f"  DOI: {doi} ({count} entries)")
            print(f"    IDs: {ids}")
            print(f"    Titles: {titles}")
    
    # Check title+year duplicates
    cursor.execute("""
        SELECT title, year, COUNT(*) as count, GROUP_CONCAT(id, ', ') as ids
        FROM papers 
        WHERE title IS NOT NULL AND title != '' AND year IS NOT NULL
        GROUP BY LOWER(title), year
        HAVING COUNT(*) > 1
    """)
    title_year_duplicates = cursor.fetchall()
    
    if title_year_duplicates:
        print(f"\nTitle+Year-based duplicates found: {len(title_year_duplicates)} groups")
        for title, year, count, ids in title_year_duplicates:
            print(f"  Title: {title}")
            print(f"  Year: {year} ({count} entries)")
            print(f"    IDs: {ids}")
    
    conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Clean up duplicate entries from the papers database')
    parser.add_argument('db_file', help='SQLite database file path')
    parser.add_argument('--preview', action='store_true', help='Preview duplicates without deleting')
    args = parser.parse_args()
    
    if args.preview:
        preview_duplicates(args.db_file)
    else:
        print("This will permanently delete duplicate entries from your database.")
        print("The script will keep the entry with the most complete information.")
        response = input("Are you sure you want to continue? (yes/no): ")
        if response.lower() in ['yes', 'y']:
            find_and_remove_duplicates(args.db_file)
        else:
            print("Operation cancelled.")