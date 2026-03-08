#!/usr/bin/env python3
"""
ResearchParça v1.2 - Main Data Regeneration Script (FIXED)

Regenerates all main averaged classification data from the three independent sets.
Uses BEST SET (highest verifier score) for text fields instead of hardcoded set_1.
"""

import sqlite3
import json
import os
import sys
from datetime import datetime
from typing import Dict, List, Tuple, Any, Optional

# ============================================================================
# CONFIGURATION
# ============================================================================

DATABASE_FILE = os.path.join(os.getcwd(), 'data', 'db.sqlite')

BOOLEAN_FIELDS = [
    'is_offtopic', 
    'is_survey', 
    'is_through_hole', 
    'is_smt', 
    'is_x_ray'
]

BOOLEAN_FEATURE_KEYS = [
    'tracks',
    'holes',
    'bare_pcb_other',
    'solder_insufficient',
    'solder_excess',
    'solder_void',
    'solder_crack',
    'solder_other',
    'orientation',
    'wrong_component',
    'missing_component',
    'component_other',
    'cosmetic'
]

BOOLEAN_TECHNIQUE_KEYS = [
    'classic_cv_based',
    'ml_traditional',
    'dl_cnn_classifier',
    'dl_cnn_detector',
    'dl_rcnn_detector',
    'dl_transformer',
    'dl_other',
    'hybrid',
    'available_dataset'
]

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def calculate_field_certainty(values: List[Optional[int]]) -> Tuple[Optional[int], str]:
    """Calculate majority vote and certainty for a field across 3 sets."""
    if not values or len(values) != 3:
        return None, 'solid'
    
    yes_count = sum(1 for v in values if v == 1)
    no_count = sum(1 for v in values if v == 0)
    null_count = sum(1 for v in values if v is None or v == '')
    
    if yes_count > no_count:
        main_value = 1
        has_disagreement = (no_count > 0)
    elif no_count > yes_count:
        main_value = 0
        has_disagreement = (yes_count > 0)
    else:
        main_value = None
        has_disagreement = True
    
    if has_disagreement and yes_count > 0 and no_count > 0:
        certainty = 'conflict'
    elif null_count == 2:
        certainty = '60'
    elif null_count == 1:
        certainty = '80'
    else:
        certainty = 'solid'
    
    return main_value, certainty


def get_best_set_for_text_fields(paper_data: Dict) -> int:
    """
    Determine which set (1, 2, or 3) has the highest verifier score.
    Returns the set number to use for text field values.
    """
    set_scores = []
    for set_num in [1, 2, 3]:
        verified = paper_data.get(f'set_{set_num}_last_llm_verified')
        score = paper_data.get(f'set_{set_num}_last_llm_estimated_score')
        
        if verified == 1 and score is not None:
            set_scores.append((set_num, score + 1000))  # Verified gets priority boost
        elif verified == 1:
            set_scores.append((set_num, 1000))
        elif score is not None:
            set_scores.append((set_num, score))
        else:
            set_scores.append((set_num, 0))
    
    best_set = max(set_scores, key=lambda x: x[1])[0]
    return best_set


def extract_set_data(paper_data: Dict, set_num: int) -> Dict:
    """Extract all classification data for a specific set."""
    prefix = f'set_{set_num}_last_llm_'
    
    data = {}
    for field in ['is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray', 
                  'relevance', 'verified', 'estimated_score']:
        data[field] = paper_data.get(f'{prefix}{field}')
    
    # Extract JSON fields
    features_str = paper_data.get(f'{prefix}features')
    technique_str = paper_data.get(f'{prefix}technique')
    
    try:
        data['features'] = json.loads(features_str) if features_str else {}
    except:
        data['features'] = {}
    
    try:
        data['technique'] = json.loads(technique_str) if technique_str else {}
    except:
        data['technique'] = {}
    
    return data


# ============================================================================
# MAIN REGENERATION LOGIC
# ============================================================================

def regenerate_paper_main_data(cursor: sqlite3.Cursor, paper_id: str) -> Optional[Dict]:
    """
    Regenerate main averaged data for a single paper from its 3 sets.
    Uses BEST SET for text fields (model, research_area, features.other).
    """
    cursor.execute("SELECT * FROM papers WHERE id = ?", (paper_id,))
    paper = cursor.fetchone()
    
    if not paper:
        print(f"  ⚠️  Paper {paper_id} not found")
        return None
    
    paper = dict(paper)
    changed_timestamp = datetime.utcnow().isoformat() + 'Z'
    
    # === DETERMINE BEST SET FOR TEXT FIELDS ===
    best_set_num = get_best_set_for_text_fields(paper)
    best_set_data = extract_set_data(paper, best_set_num)
    
    print(f"  Paper {paper_id}: Using Set {best_set_num} for text fields " +
          f"(verified={best_set_data.get('verified')}, score={best_set_data.get('estimated_score')})")
    
    # Build certainty map AND main output data
    certainty_map = {}
    main_output = {}
    
    # Process boolean classification fields
    for field in BOOLEAN_FIELDS:
        values = [
            paper.get(f'set_1_last_llm_{field}'),
            paper.get(f'set_2_last_llm_{field}'),
            paper.get(f'set_3_last_llm_{field}'),
        ]
        main_value, certainty = calculate_field_certainty(values)
        certainty_map[field] = certainty
        main_output[field] = main_value
    
    # Process relevance (numeric average)
    relevance_values = [
        paper.get('set_1_last_llm_relevance'),
        paper.get('set_2_last_llm_relevance'),
        paper.get('set_3_last_llm_relevance'),
    ]
    relevance_valid = [v for v in relevance_values if v is not None]
    main_relevance = sum(relevance_valid) / len(relevance_valid) if relevance_valid else None
    main_output['relevance'] = main_relevance
    
    # Process verified (all 3 must be verified)
    verified_values = [
        paper.get('set_1_last_llm_verified'),
        paper.get('set_2_last_llm_verified'),
        paper.get('set_3_last_llm_verified'),
    ]
    main_verified = 1 if all(v == 1 for v in verified_values) else (0 if any(v == 0 for v in verified_values) else None)
    main_output['verified'] = main_verified
    
    # Process estimated_score (average of verified sets)
    score_values = [
        paper.get('set_1_last_llm_estimated_score'),
        paper.get('set_2_last_llm_estimated_score'),
        paper.get('set_3_last_llm_estimated_score'),
    ]
    score_valid = [v for v in score_values if v is not None]
    main_score = sum(score_valid) / len(score_valid) if score_valid else None
    main_output['estimated_score'] = int(main_score) if main_score is not None else None
    
    # Process features JSON fields (boolean only)
    main_features = {}
    for feature_key in BOOLEAN_FEATURE_KEYS:
        values = []
        for sn in [1, 2, 3]:
            feat_key = f'set_{sn}_last_llm_features'
            feat_str = paper.get(feat_key)
            try:
                feat = json.loads(feat_str) if feat_str else {}
            except:
                feat = {}
            values.append(feat.get(feature_key))
        main_value, certainty = calculate_field_certainty(values)
        field_name = f'features_{feature_key}'
        certainty_map[field_name] = certainty
        main_features[feature_key] = main_value
    
    # === COPY TEXT FIELDS FROM BEST SET ===
    # features.other (text field - not averaged)
    main_features['other'] = best_set_data['features'].get('other', '')
    
    main_output['features'] = main_features
    
    # Process technique JSON fields (boolean only)
    main_technique = {}
    for tech_key in BOOLEAN_TECHNIQUE_KEYS:
        if tech_key == 'available_dataset':
            continue  # Handle separately as text field
        values = []
        for sn in [1, 2, 3]:
            tech_key_db = f'set_{sn}_last_llm_technique'
            tech_str = paper.get(tech_key_db)
            try:
                tech = json.loads(tech_str) if tech_str else {}
            except:
                tech = {}
            values.append(tech.get(tech_key))
        main_value, certainty = calculate_field_certainty(values)
        field_name = f'technique_{tech_key}'
        certainty_map[field_name] = certainty
        main_technique[tech_key] = main_value
    
    # === COPY TEXT FIELDS FROM BEST SET ===
    # technique.model (text field - not averaged)
    main_technique['model'] = best_set_data['technique'].get('model', '')
    # technique.available_dataset (boolean but from best set for consistency)
    main_technique['available_dataset'] = best_set_data['technique'].get('available_dataset')
    
    main_output['technique'] = main_technique
    
    # === COPY RESEARCH AREA FROM BEST SET ===
    # research_area is NOT in the set_* columns in current schema
    # It's only in the main columns, so we keep existing value
    # If you add set_X_research_area columns, extract from best set here
    cursor.execute("SELECT research_area FROM papers WHERE id = ?", (paper_id,))
    existing_research_area = cursor.fetchone()[0]
    main_output['research_area'] = existing_research_area
    
    # Return the calculated data
    return {
        'main_output': main_output,
        'main_features': main_features,
        'main_technique': main_technique,
        'certainty_map': certainty_map,
        'main_relevance': main_relevance,
        'main_verified': main_verified,
        'main_score': main_output['estimated_score'],
        'changed_timestamp': changed_timestamp,
        'best_set_num': best_set_num
    }


def update_paper_main_data(cursor: sqlite3.Cursor, paper_id: str, data: Dict) -> None:
    """Update a paper's main columns with regenerated data."""
    # Update main classification fields
    for field in BOOLEAN_FIELDS:
        cursor.execute(
            f"UPDATE papers SET {field} = ? WHERE id = ?",
            (data['main_output'][field], paper_id)
        )
    
    # Update relevance
    cursor.execute("UPDATE papers SET relevance = ? WHERE id = ?", (data['main_relevance'], paper_id))
    
    # Update verified
    cursor.execute("UPDATE papers SET verified = ? WHERE id = ?", (data['main_verified'], paper_id))
    
    # Update estimated_score
    cursor.execute("UPDATE papers SET estimated_score = ? WHERE id = ?", (data['main_score'], paper_id))
    
    # Update features
    cursor.execute("UPDATE papers SET features = ? WHERE id = ?", (json.dumps(data['main_features']), paper_id))
    
    # Update technique
    cursor.execute("UPDATE papers SET technique = ? WHERE id = ?", (json.dumps(data['main_technique']), paper_id))
    
    # Update main_certainty
    cursor.execute("UPDATE papers SET main_certainty = ? WHERE id = ?", (json.dumps(data['certainty_map']), paper_id))
    
    # Update last_llm_* cache fields (mirror main columns for backward compatibility)
    cursor.execute("""
    UPDATE papers SET
    last_llm_features = features,
    last_llm_technique = technique,
    last_llm_is_offtopic = is_offtopic,
    last_llm_is_survey = is_survey,
    last_llm_is_through_hole = is_through_hole,
    last_llm_is_smt = is_smt,
    last_llm_is_x_ray = is_x_ray,
    last_llm_relevance = relevance,
    last_llm_verified = verified,
    last_llm_estimated_score = estimated_score
    WHERE id = ?
    """, (paper_id,))


def regenerate_history_log(cursor: sqlite3.Cursor, paper_id: str, data: Dict) -> None:
    """Replace paper's llm_log with fresh averaged entry."""
    log_entry = {
        "timestamp": data['changed_timestamp'],
        "type": "averaged_llm",
        "model": "averaged_3_sets",
        "trace": f"Averaged from set_1, set_2, set_3. Text fields from best set (Set {data['best_set_num']})",
        "output": json.dumps({
            **data['main_output'],
            "certainty_map": data['certainty_map'],
            "best_set_for_text": data['best_set_num']
        }),
        "valid": True,
        "certainty_map": data['certainty_map']
    }
    
    cursor.execute("UPDATE papers SET llm_log = ? WHERE id = ?", (json.dumps([log_entry]), paper_id))


def regenerate_all_papers(db_path: str = None) -> None:
    """Regenerate main data for ALL papers in the database."""
    if db_path is None:
        db_path = DATABASE_FILE
    
    if not os.path.exists(db_path):
        print(f"❌ Database file not found: {db_path}")
        sys.exit(1)
    
    print(f"📊 ResearchParça v1.2 - Main Data Regeneration (BEST SET FOR TEXT)")
    print(f"📁 Database: {db_path}")
    print(f"⏰ Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM papers ORDER BY id")
    paper_ids = [row[0] for row in cursor.fetchall()]
    
    total_papers = len(paper_ids)
    print(f"📚 Found {total_papers} papers to process")
    print("=" * 70)
    
    success_count = 0
    error_count = 0
    no_data_count = 0
    
    # Track best set distribution
    best_set_distribution = {1: 0, 2: 0, 3: 0}
    
    for i, paper_id in enumerate(paper_ids, 1):
        try:
            data = regenerate_paper_main_data(cursor, paper_id)
            
            if data is None:
                error_count += 1
                continue
            
            has_set_data = any([
                data['main_output'].get('is_offtopic') is not None,
                data['main_output'].get('is_survey') is not None,
            ])
            
            if not has_set_data:
                no_data_count += 1
                if i % 100 == 0:
                    print(f"  ⚠️  {no_data_count} papers have no set data yet...")
            else:
                update_paper_main_data(cursor, paper_id, data)
                regenerate_history_log(cursor, paper_id, data)
                
                success_count += 1
                best_set_distribution[data['best_set_num']] += 1
            
            if i % 100 == 0 or i == total_papers:
                print(f"  ⏳ Processed {i}/{total_papers} papers ({100*i/total_papers:.1f}%)")
            
            if i % 100 == 0:
                conn.commit()
                
        except Exception as e:
            error_count += 1
            print(f"  ❌ Error processing paper {paper_id}: {e}")
            if i % 100 == 0:
                conn.commit()
    
    conn.commit()
    conn.close()
    
    # Print summary
    print("=" * 70)
    print(f"✅ Regeneration Complete!")
    print(f"📊 Summary:")
    print(f"   • Total papers: {total_papers}")
    print(f"   • Successfully regenerated: {success_count}")
    print(f"   • No set data yet: {no_data_count}")
    print(f"   • Errors: {error_count}")
    print(f"📈 Best Set Distribution:")
    print(f"   • Set 1: {best_set_distribution[1]} papers ({100*best_set_distribution[1]/max(success_count,1):.1f}%)")
    print(f"   • Set 2: {best_set_distribution[2]} papers ({100*best_set_distribution[2]/max(success_count,1):.1f}%)")
    print(f"   • Set 3: {best_set_distribution[3]} papers ({100*best_set_distribution[3]/max(success_count,1):.1f}%)")
    print(f"⏰ Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    if error_count > 0:
        print(f"\n⚠️  {error_count} papers had errors. Check output above for details.")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
        print(f"📁 Using custom database path: {db_path}")
        regenerate_all_papers(db_path)
    else:
        regenerate_all_papers()