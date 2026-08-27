# queue/routes.py
import json
import os
import threading
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from shared import config, db

from .logging_utils import (
    LOG_DIR,
    Colors,
    _color_mode,
    _color_prefix,
    log,
    log_file_request,
)
from .state import (
    ClassificationStateMachine,
    ConsensusStateMachine,
    VerificationStateMachine,
    log_queue_status,
    state,
)

queue_bp = Blueprint('queue', __name__)

@queue_bp.route('/reload_config', methods=['POST'])
def handle_reload_config():
    """IPC endpoint: Forces the queue manager to hot-reload domain config."""
    config.reload_domain_config()
    log(f"{_color_prefix('RELOAD:', Colors.DISPATCHER)} Domain configuration reloaded from disk.")
    return jsonify({'status': 'success'}), 200


@queue_bp.route('/classify', methods=['POST'])
def handle_classify_route():
    """Handle classification request (single paper or batch)."""
    client = request.remote_addr
    data = request.get_json(silent=True) or {}
    paper_id = data.get('paper_id')
    mode = data.get('mode', 'id')
    log(f"{_color_prefix('REQUEST:', Colors.REQUEST)} from {client}: /classify mode={_color_mode(mode)} paper_id={paper_id}")
    log_file_request('/classify', client, mode, paper_id)

    try:
        prompt_template = config.PROMPT_TEMPLATE
        model_alias = config.get_model_alias(config.LLM_SERVER_URL)
    except Exception as e:
        return jsonify({'error': f'Failed to get prompt template: {e}'}), 500

    if mode == 'id' and paper_id:
        # Single paper - NO DB connection held here. 
        # State machines will do their own short-lived DB lookups via db.get_paper_by_id()
        log(f"{_color_prefix('[CLASSIFY]', Colors.CLASSIFY)} Single paper: {paper_id} (3 sets)")
        completion_events = [threading.Event() for _ in range(3)]
        for set_num in [1, 2, 3]:
            sm = ClassificationStateMachine(paper_id, set_num, prompt_template, model_alias)
            def make_callback(set_n, event):
                def callback(pid, sn, success):
                    log(f"{_color_prefix('[CLASSIFY]', Colors.CLASSIFY)} paper={pid} set={sn} complete success={success}")
                    event.set()
                return callback
            sm.completion_callback = make_callback(set_num, completion_events[set_num - 1])
            
            # get_prompts() briefly touches the DB, formats the string, and returns
            tasks = sm.get_prompts()
            for task in tasks:
                state.enqueue(task)
                
        log(f"Enqueued 3 tasks for paper {paper_id}")
        log_queue_status()
        
        # Wait for background threads OUTSIDE of any DB context
        for event in completion_events:
            event.wait()
            
        return jsonify({'status': 'complete', 'paper_id': paper_id}), 200

    else:
        # Batch modes
        # 1. STRICT DB PHASE: Fetch data and immediately release connection
        with db.get_db() as conn:
            cursor = conn.cursor()
            if mode == 'all':
                cursor.execute("""
                    SELECT id, 1 as set_num FROM papers
                    UNION ALL SELECT id, 2 FROM papers
                    UNION ALL SELECT id, 3 FROM papers
                    ORDER BY id, set_num
                """)
            elif mode == 'remaining':
                # A set is "remaining" if the LLM blob is empty/null, or missing the universal 'is_offtopic' key
                cursor.execute("""
                    SELECT id, 1 as set_num FROM papers WHERE set_1_llm IS NULL OR set_1_llm = '' OR json_extract(set_1_llm, '$.is_offtopic') IS NULL
                    UNION ALL SELECT id, 2 FROM papers WHERE set_2_llm IS NULL OR set_2_llm = '' OR json_extract(set_2_llm, '$.is_offtopic') IS NULL
                    UNION ALL SELECT id, 3 FROM papers WHERE set_3_llm IS NULL OR set_3_llm = '' OR json_extract(set_3_llm, '$.is_offtopic') IS NULL
                    ORDER BY id, set_num
                """)
            else:
                return jsonify({'error': f'Invalid mode: {mode}'}), 400

            paper_set_pairs = cursor.fetchall()
        # --- DB CONNECTION RELEASED HERE ---

        log(f"{_color_prefix('DB QUERY:', Colors.DB)} mode={_color_mode(mode)} found {len(paper_set_pairs)} paper×set pairs")
        if not paper_set_pairs:
            log(f"WARNING: No paper×set pairs found for mode={mode}")
            return jsonify({'status': 'queued', 'papers_queued': 0}), 200

        # 2. PREPARATION PHASE: Enqueue tasks (get_prompts handles its own micro-DB lookups)
        total_tasks = 0
        for pid, set_num in paper_set_pairs:
            sm = ClassificationStateMachine(pid, set_num, prompt_template, model_alias)
            tasks = sm.get_prompts()
            for task in tasks:
                state.enqueue(task)
            total_tasks += 1

        unique_papers = len(set(p[0] for p in paper_set_pairs))
        log(f"{_color_prefix('BATCH ENQUEUE:', Colors.BATCH)} papers={unique_papers} tasks={total_tasks}")
        log_queue_status()
        return jsonify({'status': 'queued', 'papers_queued': len(paper_set_pairs), 'tasks_queued': total_tasks}), 200

@queue_bp.route('/verify', methods=['POST'])
def handle_verify_route():
    """Handle verification request (single paper or batch)."""
    client = request.remote_addr
    data = request.get_json(silent=True) or {}
    paper_id = data.get('paper_id')
    mode = data.get('mode', 'id')
    log(f"{_color_prefix('VERIFY REQUEST:', Colors.REQUEST)} from {client}: mode={_color_mode(mode)} paper_id={paper_id}")
    log_file_request('/verify', client, mode, paper_id)

    try:
        prompt_template = config.VERIFIER_TEMPLATE
        model_alias = config.get_model_alias(config.LLM_SERVER_URL)
    except Exception as e:
        log(f"ERROR: Failed to get verifier template: {e}")
        return jsonify({'error': f'Failed to get verifier template: {e}'}), 500

    if mode == 'id' and paper_id:
        log(f"Single paper verification: {paper_id} (3 sets)")
        completion_events = [threading.Event() for _ in range(3)]
        for set_num in [1, 2, 3]:
            sm = VerificationStateMachine(paper_id, set_num, prompt_template, model_alias)
            def make_callback(set_n, event):
                def callback(pid, sn, success):
                    log(f"{_color_prefix('[VERIFY]', Colors.VERIFY)} paper={pid} set={sn} complete success={success}")
                    event.set()
                return callback
            sm.completion_callback = make_callback(set_num, completion_events[set_num - 1])
            tasks = sm.get_prompts()
            for task in tasks:
                state.enqueue(task)
                
        log(f"Enqueued 3 tasks for paper {paper_id}")
        log_queue_status()
        for event in completion_events:
            event.wait()
        return jsonify({'status': 'complete', 'paper_id': paper_id}), 200
        
    else:
        # 1. STRICT DB PHASE
        with db.get_db() as conn:
            cursor = conn.cursor()
            if mode == 'all':
                cursor.execute("""
                    SELECT id, 1 as set_num FROM papers WHERE set_1_llm IS NOT NULL AND set_1_llm != '' AND json_extract(set_1_llm, '$.is_offtopic') IS NOT NULL
                    UNION ALL SELECT id, 2 FROM papers WHERE set_2_llm IS NOT NULL AND set_2_llm != '' AND json_extract(set_2_llm, '$.is_offtopic') IS NOT NULL
                    UNION ALL SELECT id, 3 FROM papers WHERE set_3_llm IS NOT NULL AND set_3_llm != '' AND json_extract(set_3_llm, '$.is_offtopic') IS NOT NULL
                    ORDER BY id, set_num
                """)
            elif mode == 'remaining':
                # A set needs verification if it has been classified, but lacks the universal 'verified' key
                cursor.execute("""
                    SELECT id, 1 as set_num FROM papers WHERE set_1_llm IS NOT NULL AND set_1_llm != '' AND (json_extract(set_1_llm, '$.verified') IS NULL OR json_extract(set_1_llm, '$.verified') = '')
                    UNION ALL SELECT id, 2 FROM papers WHERE set_2_llm IS NOT NULL AND set_2_llm != '' AND (json_extract(set_2_llm, '$.verified') IS NULL OR json_extract(set_2_llm, '$.verified') = '')
                    UNION ALL SELECT id, 3 FROM papers WHERE set_3_llm IS NOT NULL AND set_3_llm != '' AND (json_extract(set_3_llm, '$.verified') IS NULL OR json_extract(set_3_llm, '$.verified') = '')
                    ORDER BY id, set_num
                """)
            else:
                return jsonify({'error': f'Invalid mode: {mode}'}), 400

            paper_set_pairs = cursor.fetchall()
        # --- DB CONNECTION RELEASED HERE ---

        log(f"{_color_prefix('DB QUERY:', Colors.DB)} mode={_color_mode(mode)} found {len(paper_set_pairs)} paper×set pairs")
        if not paper_set_pairs:
            return jsonify({'status': 'queued', 'papers_queued': 0}), 200

        # 2. PREPARATION PHASE
        total_tasks = 0
        for pid, set_num in paper_set_pairs:
            sm = VerificationStateMachine(pid, set_num, prompt_template, model_alias)
            tasks = sm.get_prompts()
            for task in tasks:
                state.enqueue(task)
            total_tasks += 1

        unique_papers = len(set(p[0] for p in paper_set_pairs))
        log(f"{_color_prefix('BATCH ENQUEUE:', Colors.BATCH)} papers={unique_papers} tasks={total_tasks}")
        log_queue_status()
        return jsonify({'status': 'queued', 'papers_queued': len(paper_set_pairs), 'tasks_queued': total_tasks}), 200

@queue_bp.route('/consensus', methods=['POST'])
def handle_consensus_route():
    """Handle classify-until-consensus request."""
    client = request.remote_addr
    data = request.get_json(silent=True) or {}
    paper_id = data.get('paper_id')
    mode = data.get('mode', 'id')
    log(f"{_color_prefix('CONSENSUS REQUEST:', Colors.REQUEST)} from {client}: mode={_color_mode(mode)} paper_id={paper_id}")
    log_file_request('/consensus', client, mode, paper_id)

    try:
        classify_template = config.PROMPT_TEMPLATE
        verify_template = config.VERIFIER_TEMPLATE
        reclassify_template = config.RECLASSIFY_PROMPT_TEMPLATE
        model_alias = config.get_model_alias(config.LLM_SERVER_URL)
    except Exception as e:
        log(f"ERROR: Failed to get consensus templates: {e}", Colors.ERROR)
        return jsonify({'error': f'Failed to get consensus templates: {e}'}), 500

    if mode == 'id' and paper_id:
        log(f"Single paper consensus: {paper_id} (3 sets)")
        completion_events = [threading.Event() for _ in range(3)]
        for set_num in [1, 2, 3]:
            sm = ConsensusStateMachine(
                paper_id, set_num,
                classify_template, verify_template, reclassify_template,
                model_alias
            )
            def make_callback(set_n, event):
                def callback(pid, sn, success):
                    log(f"{_color_prefix('[CONSENSUS]', Colors.CONSENSUS)} paper={pid} set={sn} complete success={success}")
                    event.set()
                return callback
            sm.completion_callback = make_callback(set_num, completion_events[set_num - 1])
            
            task = sm.get_next_task()
            if task:
                state.enqueue(task)
                
        log_queue_status()
        for event in completion_events:
            event.wait()
            
        log(f"COMPLETE: consensus paper={paper_id}")
        return jsonify({'status': 'complete', 'paper_id': paper_id}), 200
        
    else:
        # 1. STRICT DB PHASE
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, 1 as set_num FROM papers 
                WHERE set_1_llm IS NULL OR set_1_llm = '' OR json_extract(set_1_llm, '$.is_offtopic') IS NULL 
                    OR json_extract(set_1_llm, '$.verified') IS NULL 
                    OR json_extract(set_1_llm, '$.verified') IN (0, 'false', 'False') 
                    OR (json_extract(set_1_llm, '$.estimated_score') IS NOT NULL AND json_extract(set_1_llm, '$.estimated_score') <= 7)
                
                UNION ALL 
                
                SELECT id, 2 as set_num FROM papers 
                WHERE set_2_llm IS NULL OR set_2_llm = '' OR json_extract(set_2_llm, '$.is_offtopic') IS NULL 
                    OR json_extract(set_2_llm, '$.verified') IS NULL 
                    OR json_extract(set_2_llm, '$.verified') IN (0, 'false', 'False') 
                    OR (json_extract(set_2_llm, '$.estimated_score') IS NOT NULL AND json_extract(set_2_llm, '$.estimated_score') <= 7)
                
                UNION ALL 
                
                SELECT id, 3 as set_num FROM papers 
                WHERE set_3_llm IS NULL OR set_3_llm = '' OR json_extract(set_3_llm, '$.is_offtopic') IS NULL 
                    OR json_extract(set_3_llm, '$.verified') IS NULL 
                    OR json_extract(set_3_llm, '$.verified') IN (0, 'false', 'False') 
                    OR (json_extract(set_3_llm, '$.estimated_score') IS NOT NULL AND json_extract(set_3_llm, '$.estimated_score') <= 7)
                
                ORDER BY id, set_num
            """)
            paper_set_pairs = cursor.fetchall()
        # --- DB CONNECTION RELEASED HERE ---
        
        log(f"{_color_prefix('DB QUERY:', Colors.DB)} mode={_color_mode(mode)} found {len(paper_set_pairs)} paper×set pairs")
        if not paper_set_pairs:
            log("WARNING: No paper×set pairs need consensus")
            return jsonify({'status': 'queued', 'papers_queued': 0}), 200

        # 2. PREPARATION PHASE
        total_tasks = 0
        for pid, set_num in paper_set_pairs:
            sm = ConsensusStateMachine(
                pid, set_num,
                classify_template, verify_template, reclassify_template,
                model_alias
            )
            task = sm.get_next_task()
            if task:
                state.enqueue(task)
                total_tasks += 1

        unique_papers = len(set(p[0] for p in paper_set_pairs))
        log(f"{_color_prefix('BATCH ENQUEUE:', Colors.BATCH)} papers={unique_papers} tasks={total_tasks}")
        log_queue_status()
        return jsonify({'status': 'queued', 'papers_queued': len(paper_set_pairs), 'tasks_queued': total_tasks}), 200


@queue_bp.route('/review_traces', methods=['POST'])
def handle_review_traces():
    """Free-form LLM meta-review of a paper's complete 3-set log stream.

    Manual, single-paper, synchronous. Deliberately NOT enqueued/dispatched —
    it runs inline in this request thread, bypassing admission control by design.
    Appends a 'trace_review' entry to the main llm_log; does NOT recalculate it.
    """
    client = request.remote_addr
    data = request.get_json(silent=True) or {}
    paper_id = data.get('paper_id')
    log(f"{_color_prefix('REVIEW REQUEST:', Colors.REQUEST)} from {client}: /review_traces paper_id={paper_id}")
    log_file_request('/review_traces', client, 'id', paper_id)

    if not paper_id:
        return jsonify({'status': 'error', 'message': 'Paper ID is required'}), 400

    paper = db.get_paper_by_id(paper_id)
    if not paper:
        return jsonify({'status': 'error', 'message': 'Paper not found'}), 404

    def pretty_log(raw):
        try:
            entries = json.loads(raw) if raw else []
        except Exception:
            entries = []
        # Full fidelity by design — no truncation.
        return json.dumps(entries, indent=2, ensure_ascii=False)

    prompt = config.load_trace_review_base_template()
    classify_inst, classify_tmpl = config.get_classify_prompt_fragments()
    prompt = prompt.replace('{classify_instructions}', classify_inst)
    prompt = prompt.replace('{classify_output_template}', classify_tmpl)
    prompt = prompt.replace('{title}', paper.get('title', '') or '')
    prompt = prompt.replace('{abstract}', paper.get('abstract', '') or '')
    prompt = prompt.replace('{keywords}', paper.get('keywords', '') or '')
    prompt = prompt.replace('{log_set_1}', pretty_log(paper.get('set_1_llm_log')))
    prompt = prompt.replace('{log_set_2}', pretty_log(paper.get('set_2_llm_log')))
    prompt = prompt.replace('{log_set_3}', pretty_log(paper.get('set_3_llm_log')))

    # Persist the exact prompt sent to the model, for debugging/auditing.
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    try:
        dump_dir = os.path.join(LOG_DIR, 'trace_reviews')
        os.makedirs(dump_dir, exist_ok=True)
        prompt_dump_path = os.path.join(dump_dir, f"trace_review_prompt_{paper_id}_{timestamp}.txt")
        with open(prompt_dump_path, 'w', encoding='utf-8') as f:
            f.write(prompt)
        log(f"{_color_prefix('REVIEW:', Colors.CONSENSUS)} Prompt dumped to {prompt_dump_path}")
    except Exception as e:
        # A dump failure must never block the review itself.
        log(f"{_color_prefix('ERROR:', Colors.ERROR)} Failed to dump trace review prompt: {e}")

    try:
        model_alias = config.get_model_alias(config.LLM_SERVER_URL)
        content, model_name, reasoning_trace = config.send_prompt_to_llm(
            prompt, model_name=model_alias, is_verification=False
        )
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Trace review failed: {e}'}), 502

    if content is None:
        # On failure send_prompt_to_llm returns the error message in the trace slot
        return jsonify({'status': 'error', 'message': reasoning_trace or 'LLM call failed'}), 502

    db.append_trace_review_log(paper_id, model_name, reasoning_trace, content, valid=True)
    log(f"{_color_prefix('COMPLETE:', Colors.VLLM_COMPLETE)} trace review paper={paper_id}")
    return jsonify({'status': 'success', 'paper_id': paper_id})

@queue_bp.app_errorhandler(404)
def not_found(e):
    log(f"{_color_prefix('ERROR:', Colors.ERROR)} Unknown endpoint {request.path}")
    return jsonify({'error': 'Not found'}), 404

@queue_bp.app_errorhandler(400)
def bad_request(e):
    log(f"{_color_prefix('ERROR:', Colors.ERROR)} Invalid JSON in request")
    return jsonify({'error': 'Invalid JSON'}), 400