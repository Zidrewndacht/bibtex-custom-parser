#!/usr/bin/env python3
"""
regenerate_main_averages.py

REGENERATES all main averaged classification data from the 3 independent classification sets.
COMPLETELY REPLACES existing main history with a single fresh averaged_llm entry.
"""

import sqlite3
import json
import sys
import os
from datetime import datetime

def calculate_field_certainty(values):
    """
    Calculate the majority vote and certainty for a field across 3 sets.
    Returns: (main_value, certainty_string)
    - main_value: 1, 0, or None (majority vote, None = unknown)
    - certainty_string: 'solid', '80', '60', or 'conflict'
    """
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


def get_best_set_for_text_fields(paper_data):
    """Determine which set has the highest verifier score."""
    set_scores = []
    for set_num in [1, 2, 3]:
        verified = paper_data.get(f'set_{set_num}_last_llm_verified')
        score = paper_data.get(f'set_{set_num}_last_llm_estimated_score')
        
        if verified == 1 and score is not None:
            set_scores.append((set_num, score + 1000))
        elif verified == 1:
            set_scores.append((set_num, 1000))
        elif score is not None:
            set_scores.append((set_num, score))
        else:
            set_scores.append((set_num, 0))
    
    return max(set_scores, key=lambda x: x[1])[0]

def regenerate_paper_main_set(cursor, paper_id, paper_data):
    """
    Regenerate main averaged set from the 3 classification sets.
    Only uses valid set data.
    """
    changed_timestamp = datetime.utcnow().isoformat() + 'Z'
    certainty_map = {}
    main_output = {}
    
    # =========================================================================
    # 1. Boolean classification fields
    # =========================================================================
    boolean_fields = ['is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray']
    
    for field in boolean_fields:
        values = [
            paper_data.get(f'set_1_last_llm_{field}'),
            paper_data.get(f'set_2_last_llm_{field}'),
            paper_data.get(f'set_3_last_llm_{field}'),
        ]
        main_value, certainty = calculate_field_certainty(values)
        certainty_map[field] = certainty
        main_output[field] = main_value
        cursor.execute(f"UPDATE papers SET {field} = ? WHERE id = ?", (main_value, paper_id))
    
    # =========================================================================
    # 2. Numeric fields - MUST ALWAYS EXIST
    # =========================================================================
    relevance_values = [
        paper_data.get('set_1_last_llm_relevance'),
        paper_data.get('set_2_last_llm_relevance'),
        paper_data.get('set_3_last_llm_relevance'),
    ]
    relevance_valid = [v for v in relevance_values if v is not None]
    main_relevance = sum(relevance_valid) / len(relevance_valid) if relevance_valid else None
    main_output['relevance'] = main_relevance
    cursor.execute("UPDATE papers SET relevance = ? WHERE id = ?", (main_relevance, paper_id))
    
    score_values = [
        paper_data.get('set_1_last_llm_estimated_score'),
        paper_data.get('set_2_last_llm_estimated_score'),
        paper_data.get('set_3_last_llm_estimated_score'),
    ]
    score_valid = [v for v in score_values if v is not None]
    main_score = sum(score_valid) / len(score_valid) if score_valid else None
    main_output['estimated_score'] = int(main_score) if main_score is not None else None
    cursor.execute("UPDATE papers SET estimated_score = ? WHERE id = ?", (main_output['estimated_score'], paper_id))
    
    # =========================================================================
    # 3. Verified field
    # =========================================================================
    verified_values = [
        paper_data.get('set_1_last_llm_verified'),
        paper_data.get('set_2_last_llm_verified'),
        paper_data.get('set_3_last_llm_verified'),
    ]
    main_verified, verified_certainty = calculate_field_certainty(verified_values)
    certainty_map['verified'] = verified_certainty
    main_output['verified'] = main_verified
    cursor.execute("UPDATE papers SET verified = ? WHERE id = ?", (main_verified, paper_id))
    
    # =========================================================================
    # 4. Features JSON fields
    # =========================================================================
    BOOLEAN_FEATURE_KEYS = [
        'tracks', 'holes', 'bare_pcb_other', 'solder_insufficient',
        'solder_excess', 'solder_void', 'solder_crack', 'solder_other',
        'orientation', 'wrong_component', 'missing_component',
        'component_other', 'cosmetic'
    ]
    
    main_features = {}
    for feature_key in BOOLEAN_FEATURE_KEYS:
        values = []
        for sn in [1, 2, 3]:
            feat_str = paper_data.get(f'set_{sn}_last_llm_features')
            try:
                feat = json.loads(feat_str) if feat_str else {}
            except:
                feat = {}
            values.append(feat.get(feature_key))
        
        main_value, certainty = calculate_field_certainty(values)
        field_name = f'features_{feature_key}'
        certainty_map[field_name] = certainty
        main_features[feature_key] = main_value  # ← ALWAYS present (can be None)
    
    # Text field from best set
    best_set = get_best_set_for_text_fields(paper_data)
    try:
        feat_str = paper_data.get(f'set_{best_set}_last_llm_features')
        feat_best = json.loads(feat_str) if feat_str else {}
        main_features['other'] = feat_best.get('other')  # ← ALWAYS present (can be None)
    except:
        main_features['other'] = None
    
    main_output['features'] = main_features  # ← ALWAYS present
    cursor.execute("UPDATE papers SET features = ? WHERE id = ?", (json.dumps(main_features), paper_id))
    
    # =========================================================================
    # 5. Technique JSON fields
    # =========================================================================
    DEFAULT_TECHNIQUE_KEYS = [
        'classic_cv_based', 'ml_traditional', 'dl_cnn_classifier',
        'dl_cnn_detector', 'dl_rcnn_detector', 'dl_transformer',
        'dl_other', 'hybrid', 'available_dataset'
    ]
    
    main_technique = {}
    for tech_key in DEFAULT_TECHNIQUE_KEYS:
        values = []
        for sn in [1, 2, 3]:
            tech_str = paper_data.get(f'set_{sn}_last_llm_technique')
            try:
                tech = json.loads(tech_str) if tech_str else {}
            except:
                tech = {}
            values.append(tech.get(tech_key))
        
        main_value, certainty = calculate_field_certainty(values)
        field_name = f'technique_{tech_key}'
        certainty_map[field_name] = certainty
        main_technique[tech_key] = main_value  # ← ALWAYS present (can be None)
    
    # Text fields from best set
    try:
        tech_str = paper_data.get(f'set_{best_set}_last_llm_technique')
        tech_best = json.loads(tech_str) if tech_str else {}
        main_technique['model'] = tech_best.get('model')  # ← ALWAYS present
        main_technique['available_dataset'] = tech_best.get('available_dataset')
    except:
        main_technique['model'] = None
        main_technique['available_dataset'] = None
    
    main_output['technique'] = main_technique  # ← ALWAYS present
    cursor.execute("UPDATE papers SET technique = ? WHERE id = ?", (json.dumps(main_technique), paper_id))
    
    # =========================================================================
    # 6. Update main_certainty column
    # =========================================================================
    cursor.execute("UPDATE papers SET main_certainty = ? WHERE id = ?", (json.dumps(certainty_map), paper_id))
    
    # =========================================================================
    # 7. Update last_llm_* cache fields
    # =========================================================================
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
    
    # =========================================================================
    # 8. COMPLETELY REPLACE main history (llm_log) with ONE fresh entry
    # =========================================================================
    
    # CRITICAL: Ensure ALL fields expected by template are in main_output
    # Template expects: is_offtopic, relevance, is_survey, is_through_hole, is_smt, is_x_ray,
    #                   verified, estimated_score, features (with all keys), technique (with all keys)
    
    log_entry = {
        "timestamp": changed_timestamp,
        "type": "averaged_llm",
        "model": "averaged_3_sets",
        "trace": f"Averaged from 3 classification sets (regenerated)",
        "output": json.dumps(main_output),  # ← All fields guaranteed present above
        "valid": True,
        "certainty_map": certainty_map  # ← At top level for template access
    }
    
    # =========================================================================
    # 9. Replace main history with ONE fresh entry
    # =========================================================================
    # Validate main_output has all required fields before creating log entry
    required_fields = ['is_offtopic', 'is_survey', 'is_through_hole', 'is_smt', 'is_x_ray',
                      'relevance', 'verified', 'estimated_score', 'features', 'technique']
    missing = [f for f in required_fields if f not in main_output]
    if missing:
        print(f"ERROR: Paper {paper_id} missing fields: {missing}")
        return None
    
    log_entry = {
        "timestamp": changed_timestamp,
        "type": "averaged_llm",
        "model": "averaged_3_sets",
        "trace": f"Averaged from 3 classification sets (regenerated)",
        "output": json.dumps({
            **main_output,
            "certainty_map": certainty_map
        }),
        "valid": True,  # ← Explicitly mark as valid
        "certainty_map": certainty_map
    }
    
    new_log = [log_entry]
    cursor.execute("UPDATE papers SET llm_log = ? WHERE id = ?", (json.dumps(new_log), paper_id))
    
    return certainty_map


def main():
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        db_path = os.path.join(os.getcwd(), 'data', 'db.sqlite')
    
    if not os.path.exists(db_path):
        print(f"Error: Database file not found: {db_path}")
        sys.exit(1)
    
    print(f"Connecting to database: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM papers")
    paper_ids = [row[0] for row in cursor.fetchall()]
    total_papers = len(paper_ids)
    
    print(f"Found {total_papers} papers to process")
    print("=" * 60)
    
    processed = 0
    errors = 0
    
    for paper_id in paper_ids:
        try:
            cursor.execute("SELECT * FROM papers WHERE id = ?", (paper_id,))
            paper_data = dict(cursor.fetchone())
            
            regenerate_paper_main_set(cursor, paper_id, paper_data)
            
            processed += 1
            if processed % 100 == 0 or processed == total_papers:
                print(f"Progress: {processed}/{total_papers} papers ({100*processed//total_papers}%)")
            
        except Exception as e:
            errors += 1
            print(f"Error processing paper {paper_id}: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    conn.commit()
    conn.close()
    
    print("=" * 60)
    print(f"Regeneration complete!")
    print(f"  Processed: {processed}/{total_papers} papers")
    print(f"  Errors: {errors}")
    print(f"  Database: {db_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()