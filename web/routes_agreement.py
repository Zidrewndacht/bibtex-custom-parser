# web/routes_agreement.py
"""
Whole-dataset 3-Run Agreement Report.

Deliberately NOT part of the static HTML export and NOT affected by active
filters: it always analyzes the entire database. Opened from the Batch Tasks
modal in a new tab. Outlier links open plain new tabs (target=_blank) with a
narrowly-scoped URL: the paper's own year as the server-side year filter
(fast render) and the paper ID as the search query (hides everything else).
"""

from datetime import datetime
from urllib.parse import urlencode

from flask import Blueprint, render_template

from shared import config
from meta import agreement_core

import sqlite3
import json
from datetime import datetime, timezone

agreement_bp = Blueprint('agreement', __name__)

def parse_timestamp(ts_str):
    """Robust timestamp parser that handles Z, +00:00, and various formats."""
    if not ts_str:
        return None
    ts_str = str(ts_str).strip()
    clean = ts_str.replace('Z', '+00:00')
    try:
        return datetime.fromisoformat(clean)
    except ValueError:
        pass
    # Fallback for older Python versions or slightly weird formats
    for fmt in ('%Y-%m-%dT%H:%M:%S.%f%z', '%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(ts_str.replace('Z', '+0000').replace('+00:00', '+0000'), fmt)
        except ValueError:
            continue
    return None

def get_consensus_progress(db_path):
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT llm_log FROM papers WHERE llm_log IS NOT NULL AND llm_log != '[]' AND llm_log != ''")
        
        completion_timestamps = []   # latest timestamp per paper (when it finished)
        earliest_ts = None           # true process start (first log entry of any kind)
        rows = cursor.fetchall()
        print(f"[Agreement Report] Found {len(rows)} papers with llm_log entries.")
        
        for (log_str,) in rows:
            try:
                logs = json.loads(log_str)
                latest_ts = None
                for entry in logs:
                    if entry.get('type') in ['averaged_llm', 'classifier', 'consensus', 'user']:
                        ts = parse_timestamp(entry.get('timestamp'))
                        if ts:
                            # Track the earliest timestamp across ALL entries = process start
                            if earliest_ts is None or ts < earliest_ts:
                                earliest_ts = ts
                            # Track the latest timestamp per paper = completion
                            if latest_ts is None or ts > latest_ts:
                                latest_ts = ts
                if latest_ts:
                    completion_timestamps.append(latest_ts)
            except Exception as e:
                print(f"[Agreement Report] Error parsing llm_log: {e}")
                continue
        conn.close()
        
        if not completion_timestamps or earliest_ts is None:
            print("[Agreement Report] No valid timestamps found for consensus progress.")
            return None
        
        # Normalize timezone awareness consistently across all timestamps
        has_tz = earliest_ts.tzinfo is not None
        if has_tz:
            earliest_ts = earliest_ts if earliest_ts.tzinfo else earliest_ts.replace(tzinfo=timezone.utc)
            completion_timestamps = [
                t if t.tzinfo is not None else t.replace(tzinfo=timezone.utc)
                for t in completion_timestamps
            ]
        else:
            earliest_ts = earliest_ts.replace(tzinfo=None) if earliest_ts.tzinfo else earliest_ts
            completion_timestamps = [
                t.replace(tzinfo=None) if t.tzinfo is not None else t
                for t in completion_timestamps
            ]
        
        completion_timestamps.sort()
        
        start = earliest_ts          # <-- process start, not first completion
        total = len(completion_timestamps)
        
        events = [{'elapsed': 0.0, 'remaining': total}]
        for i, ts in enumerate(completion_timestamps):
            elapsed = (ts - start).total_seconds() / 60.0
            events.append({'elapsed': elapsed, 'remaining': total - i - 1})
        
        return {
            'total': total,
            'duration_minutes': (completion_timestamps[-1] - start).total_seconds() / 60.0,
            'events': events
        }
    except Exception as e:
        print(f"[Agreement Report] FATAL Error building consensus progress: {e}")
        import traceback
        traceback.print_exc()
        return None
    
def build_focus_url(paper_id, year):
    """Deep link that opens the main app narrowed to a single paper."""
    params = {
        'focus_paper': paper_id,
        'search_query': paper_id,   # client-side: hides everything else
        'hide_offtopic': '0',
        'min_page_count': '0',
    }
    if year is not None:
        # Server-side: fetch only the paper's year for a fast render
        params['year_from'] = str(year)
        params['year_to'] = str(year)
    else:
        params['year_from'] = '0'
        params['year_to'] = '9999'
    return '/?' + urlencode(params)


@agreement_bp.route('/agreement_report')
def agreement_report():
    generated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Fresh domain config per request (report is opened rarely; the hot-reload
    # path in config.reload_domain_config only patches web.routes_ui).
    domain_config = config.load_domain_config()
    boolean_fields = agreement_core.discover_boolean_fields(domain_config)
    categories = agreement_core.get_field_categories(domain_config, boolean_fields)
    # Friendly, verbatim names for HTML display (LaTeX keeps the structural names)
    display_categories = agreement_core.category_display_names(domain_config, categories)
    field_labels = agreement_core.build_field_label_map(domain_config)

    papers = agreement_core.load_all_papers_from_single_db(
        config.DATABASE_FILE, boolean_fields)

    # Expensive LLM-log analysis is only needed for the 'all_papers' stratum
    # (pipeline health cards); skip it for every other stratum.
    results = agreement_core.run_analysis(
        papers, boolean_fields, config.DATABASE_FILE,
        verbose=False, log_analysis_strata={'all_papers'})

    meta = results['_meta']
    meta_summary = {
        'total_papers': meta['total_papers'],
        'on_topic': len(meta['on_topic_ids']),
        'off_topic': len(meta['off_topic_ids']),
        'undetermined': len(meta['undetermined_ids']),
        'n_fields': meta['n_fields'],
    }

    # --- LaTeX strings for the per-section copy buttons ---
    latex_map = {name: content
                 for name, content in agreement_core.build_latex_tables(results, categories)}

    # --- JSON-safe chart data ---
    report_data = {
        'strata': {
            name: agreement_core.stratum_summary(results[name])
            for name in ('all_papers', 'on_topic_only', 'off_topic_only')
        },
        'relevance_bins': [],
    }
    for low, high, label in agreement_core.RELEVANCE_BINS:
        # Relevance 0-1 is always off-topic, so this bin is guaranteed empty
        # for on-topic papers. Skip it (the LaTeX tables already omit it).
        if low == 0 and high == 1:
            continue
        key = agreement_core.relevance_stratum_key(label)
        s = results.get(key)
        if s is None:
            continue
        summ = agreement_core.stratum_summary(s)
        summ['label'] = label
        report_data['relevance_bins'].append(summ)
        
    # --- Per-field table (on-topic), grouped by category, best-first ---
    on_topic = results['on_topic_only']
    field_records = []
    if not on_topic['field_results'].empty:
        sorted_df = on_topic['field_results'].sort_values(
            'perfect_pct', ascending=False)
        for row in sorted_df.to_dict('records'):
            row['field_formatted'] = (field_labels.get(row['field'])
                                      or agreement_core.format_field_name(row['field']))
            field_records.append(row)

    fields_by_category = []
    for cat_name, cat_fields in display_categories:
        rows = [r for r in field_records if r['field'] in cat_fields]
        if rows:
            fields_by_category.append((cat_name, rows))

    # --- Category-level summaries ---
    cat_summaries = agreement_core.category_summaries(results, display_categories, field_labels)

    # --- Pipeline health (all papers) ---
    all_papers_stratum = results['all_papers']
    log_stats = all_papers_stratum.get('log_stats', {}) or {}
    consensus_stats = all_papers_stratum.get('consensus_stats', {}) or {}
    per_set = []
    for col, st in (log_stats.get('per_set') or {}).items():
        try:
            set_num = col.split('_')[1]  # 'set_1_llm_log' -> '1'
        except IndexError:
            set_num = '?'
        per_set.append({'set': f'Set {set_num}', **st})

    # --- Outliers (plain new-tab deep links) ---
    top_contradictory = agreement_core.collect_top_contradictory_papers(
        papers, boolean_fields, meta['on_topic_ids'], top_n=10)
    for item in top_contradictory:
        item['focus_url'] = build_focus_url(item['paper_id'], item.get('year'))

    def focus_url_for(pid):
        year = None
            # Attach focus URLs to papers with invalid log entries
        if pid in papers:
            year = papers[pid][1].get('_year')
        return build_focus_url(pid, year)

    for item in (log_stats.get('papers_with_invalid') or []):
        item['focus_url'] = focus_url_for(item['paper_id'])
        
    max_runs_focus_url = None
    max_runs_paper = consensus_stats.get('max_runs_paper')
    if max_runs_paper:
        max_runs_focus_url = focus_url_for(max_runs_paper)
    
    # Attach focus URLs + relevance to the consensus-attempt rankings
    for set_num, entries in (consensus_stats.get('top_runs_per_set') or {}).items():
        for entry in entries:
            entry['focus_url'] = focus_url_for(entry['paper_id'])
            entry['relevance'] = agreement_core.averaged_relevance(papers, entry['paper_id'])
    for entry in (consensus_stats.get('top_runs_total') or []):
        entry['focus_url'] = focus_url_for(entry['paper_id'])
        entry['relevance'] = agreement_core.averaged_relevance(papers, entry['paper_id'])
        
    consensus_progress = get_consensus_progress(config.DATABASE_FILE)

    return render_template(
        'agreement_report.html',
        domain_config=domain_config,
        generated_at=generated_at,
        meta_summary=meta_summary,
        report_data=report_data,
        latex_map=latex_map,
        on_topic_summary=report_data['strata']['on_topic_only'],
        fields_by_category=fields_by_category,
        category_summaries=cat_summaries,
        top_contradictory=top_contradictory,
        max_runs_focus_url=max_runs_focus_url,
        log_stats=log_stats,
        consensus_stats=consensus_stats,
        per_set=per_set,
        min_n_for_ci=agreement_core.MIN_N_FOR_CI,
        consensus_progress=consensus_progress,
    )