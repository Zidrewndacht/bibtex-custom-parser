# merge_databases_batch.py
import sqlite3
import shutil
import os
import argparse
from pathlib import Path

def get_all_papers(db_path):
    """Fetch all papers from a database as a dictionary keyed by paper ID."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Check if papers table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='papers'")
    if not cursor.fetchone():
        conn.close()
        raise ValueError(f"Database '{db_path}' does not contain 'papers' table")
    
    cursor.execute("SELECT * FROM papers")
    papers = {row['id']: dict(row) for row in cursor.fetchall()}
    conn.close()
    return papers

def merge_databases(db1_path, db2_path, output_path):
    """Merge two ResearchParça databases. Priority: Keep on-topic version if duplicate exists."""
    print(f"\nLoading database 1: {db1_path}")
    papers1 = get_all_papers(db1_path)
    print(f"  → {len(papers1)} papers loaded")
    
    print(f"Loading database 2: {db2_path}")
    papers2 = get_all_papers(db2_path)
    print(f"  → {len(papers2)} papers loaded")
    
    # Remove existing output file if it exists
    if os.path.exists(output_path):
        os.remove(output_path)
    
    # Copy schema from db1 to output
    shutil.copy(db1_path, output_path)
    
    # Clear all data from output
    conn_out = sqlite3.connect(output_path)
    cursor_out = conn_out.cursor()
    cursor_out.execute("DELETE FROM papers")
    conn_out.commit()
    
    # Merge papers
    merged_papers = {}
    duplicates_found = 0
    ontopic_preferred = 0
    
    # First, add all papers from db1
    for paper_id, paper_data in papers1.items():
        merged_papers[paper_id] = paper_data
    
    # Then, add papers from db2, handling duplicates
    for paper_id, paper_data in papers2.items():
        if paper_id in merged_papers:
            duplicates_found += 1
            existing = merged_papers[paper_id]
            
            existing_offtopic = existing.get('is_offtopic')
            new_offtopic = paper_data.get('is_offtopic')
            
            # Priority: Keep on-topic version (is_offtopic = 0)
            if existing_offtopic == 1 and new_offtopic == 0:
                merged_papers[paper_id] = paper_data
                ontopic_preferred += 1
                print(f"  Duplicate ID '{paper_id}': Kept ON-TOPIC version from db2")
            elif existing_offtopic == 0 and new_offtopic == 1:
                print(f"  Duplicate ID '{paper_id}': Kept ON-TOPIC version from db1")
            else:
                print(f"  Duplicate ID '{paper_id}': Both same status, kept db1 version")
        else:
            merged_papers[paper_id] = paper_data
    
    # Insert all merged papers into output database
    print(f"Inserting {len(merged_papers)} merged papers...")
    
    if merged_papers:
        sample_paper = next(iter(merged_papers.values()))
        columns = list(sample_paper.keys())
        placeholders = ', '.join(['?' for _ in columns])
        column_names = ', '.join(columns)
        
        insert_query = f"INSERT INTO papers ({column_names}) VALUES ({placeholders})"
        
        for paper_id, paper_data in merged_papers.items():
            values = [paper_data.get(col) for col in columns]
            cursor_out.execute(insert_query, values)
        
        conn_out.commit()
    
    conn_out.close()
    
    return {
        'db1_count': len(papers1),
        'db2_count': len(papers2),
        'duplicates': duplicates_found,
        'ontopic_preferred': ontopic_preferred,
        'final_count': len(merged_papers)
    }

def find_database_files(folder_path):
    """Find all .db and .sqlite files in a folder."""
    folder = Path(folder_path)
    db_files = sorted([f for f in folder.iterdir() if f.suffix in ['.db', '.sqlite'] and f.stem.isdigit()])
    return db_files

def merge_folder_pairs(folder1, folder2, output_folder):
    """Merge matching database pairs from two folders."""
    print("="*60)
    print("RESEARCHPARÇA BATCH DATABASE MERGE")
    print("="*60)
    
    db_files_1 = find_database_files(folder1)
    db_files_2 = find_database_files(folder2)
    
    print(f"\nFolder 1 ({folder1}):")
    for db in db_files_1:
        print(f"  - {db.name}")
    
    print(f"\nFolder 2 ({folder2}):")
    for db in db_files_2:
        print(f"  - {db.name}")
    
    os.makedirs(output_folder, exist_ok=True)
    
    db_names_1 = set(db.stem for db in db_files_1)
    db_names_2 = set(db.stem for db in db_files_2)
    matching_pairs = db_names_1.intersection(db_names_2)
    
    if not matching_pairs:
        print("\n❌ No matching database pairs found!")
        return False
    
    print(f"\n✓ Found {len(matching_pairs)} matching pair(s): {sorted(matching_pairs)}")
    
    results = []
    for db_name in sorted(matching_pairs, key=lambda x: int(x)):
        # Find the actual files (could be .db or .sqlite)
        db1_file = next((f for f in db_files_1 if f.stem == db_name), None)
        db2_file = next((f for f in db_files_2 if f.stem == db_name), None)
        
        if not db1_file or not db2_file:
            print(f"\n❌ Could not find matching files for {db_name}")
            continue
        
        db1_path = str(db1_file)
        db2_path = str(db2_file)
        output_path = os.path.join(output_folder, f"{db_name}_merged.sqlite")
        
        print(f"\n{'='*60}")
        print(f"Merging Pair: {db_name}")
        print(f"  DB1: {db1_path}")
        print(f"  DB2: {db2_path}")
        print(f"  Output: {output_path}")
        print(f"{'='*60}")
        
        try:
            result = merge_databases(db1_path, db2_path, output_path)
            result['name'] = db_name
            results.append(result)
            print(f"\n✓ Successfully merged {db_name} → {db_name}_merged.sqlite")
        except Exception as e:
            print(f"\n❌ Error merging {db_name}: {e}")
            results.append({'name': db_name, 'error': str(e)})
    
    # Print summary
    print("\n" + "="*60)
    print("MERGE SUMMARY")
    print("="*60)
    
    total_db1 = 0
    total_db2 = 0
    total_duplicates = 0
    total_ontopic = 0
    total_final = 0
    successful = 0
    
    for result in results:
        if 'error' in result:
            print(f"\n{result['name']}: ❌ FAILED - {result['error']}")
        else:
            successful += 1
            total_db1 += result['db1_count']
            total_db2 += result['db2_count']
            total_duplicates += result['duplicates']
            total_ontopic += result['ontopic_preferred']
            total_final += result['final_count']
            print(f"\n{result['name']}:")
            print(f"  DB1: {result['db1_count']} papers")
            print(f"  DB2: {result['db2_count']} papers")
            print(f"  Duplicates: {result['duplicates']}")
            print(f"  On-topic preferred: {result['ontopic_preferred']}")
            print(f"  Final: {result['final_count']} papers")
    
    print("\n" + "-"*60)
    print(f"Successfully merged: {successful}/{len(results)} pairs")
    print(f"Total papers (DB1): {total_db1}")
    print(f"Total papers (DB2): {total_db2}")
    print(f"Total duplicates: {total_duplicates}")
    print(f"Total on-topic preferred: {total_ontopic}")
    print(f"Total final papers: {total_final}")
    print(f"Output folder: {output_folder}")
    print("="*60)
    
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Merge matching ResearchParça database pairs from two folders')
    parser.add_argument('folder1', nargs='?', help='First folder containing database files')
    parser.add_argument('folder2', nargs='?', help='Second folder containing database files')
    parser.add_argument('-o', '--output', default='merged_output', help='Output folder for merged databases')
    
    args = parser.parse_args()
    
    # Interactive mode if folders not provided
    if not args.folder1 or not args.folder2:
        print("\n" + "="*60)
        print("ResearchParça Batch Database Merge")
        print("="*60)
        print("\nThis script will merge matching database pairs (1, 2, 3, etc.)")
        print("from two different folders, keeping on-topic versions for duplicates.\n")
        
        if not args.folder1:
            folder1 = input("Enter path to FIRST folder: ").strip()
        else:
            folder1 = args.folder1
        
        if not args.folder2:
            folder2 = input("Enter path to SECOND folder: ").strip()
        else:
            folder2 = args.folder2
        
        output_folder = input(f"Enter output folder name (default: {args.output}): ").strip()
        if not output_folder:
            output_folder = args.output
    else:
        folder1 = args.folder1
        folder2 = args.folder2
        output_folder = args.output
    
    # Validate folders
    if not os.path.isdir(folder1):
        print(f"\n❌ Error: First folder not found: {folder1}")
        exit(1)
    
    if not os.path.isdir(folder2):
        print(f"\n❌ Error: Second folder not found: {folder2}")
        exit(1)
    
    # Run the merge
    success = merge_folder_pairs(folder1, folder2, output_folder)
    
    if success:
        print("\n✓ Batch merge completed successfully!")
    else:
        print("\n❌ Batch merge completed with errors.")
        exit(1)