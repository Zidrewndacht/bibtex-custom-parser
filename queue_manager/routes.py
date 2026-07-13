# queue/routes.py
import threading
from flask import Blueprint, request, jsonify
from shared import config, db
from .logging_utils import log, log_file_request, Colors, _color_prefix, _color_mode
from .state import (
    state, log_queue_status,
    ClassificationStateMachine, VerificationStateMachine, ConsensusStateMachine
)

queue_bp = Blueprint('queue', __name__)

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
        prompt_template = config.load_prompt_template(config.PROMPT_TEMPLATE)
        model_alias = config.get_model_alias(config.LLM_SERVER_URL)
    except Exception as e:
        return jsonify({'error': f'Failed to load prompt template: {e}'}), 500

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
                cursor.execute("""
                    SELECT id, 1 as set_num FROM papers WHERE set_1_last_llm_is_offtopic IS NULL OR set_1_last_llm_is_offtopic = ''
                    UNION ALL SELECT id, 2 FROM papers WHERE set_2_last_llm_is_offtopic IS NULL OR set_2_last_llm_is_offtopic = ''
                    UNION ALL SELECT id, 3 FROM papers WHERE set_3_last_llm_is_offtopic IS NULL OR set_3_last_llm_is_offtopic = ''
                    ORDER BY id, set_num
                """)
            elif mode == 'no_features':
                set_queries = []
                for sn in [1, 2, 3]:
                    col_name = f'set_{sn}_last_llm_features'
                    conditions = [f"set_{sn}_last_llm_is_offtopic = 0"]
                    for key in config.BOOLEAN_FEATURE_KEYS:
                        conditions.append(f"""(
                            CASE 
                                WHEN {col_name} IS NULL OR {col_name} = '' THEN 1
                                WHEN json_extract({col_name}, '$.{key}') IS NULL THEN 1
                                WHEN json_extract({col_name}, '$.{key}') = 0 THEN 1
                                ELSE 0
                            END = 1
                        )""")
                    set_queries.append(f"SELECT id, {sn} as set_num FROM papers WHERE {' AND '.join(conditions)}")
                cursor.execute(f" {' UNION ALL '.join(set_queries)} ORDER BY id, set_num")
            elif mode == 'on_topic_implementation':
                cursor.execute("""
                    SELECT id, 1 as set_num FROM papers WHERE set_1_last_llm_is_offtopic = 0 AND (set_1_last_llm_is_survey = 0 OR set_1_last_llm_is_survey IS NULL)
                    UNION ALL SELECT id, 2 FROM papers WHERE set_2_last_llm_is_offtopic = 0 AND (set_2_last_llm_is_survey = 0 OR set_2_last_llm_is_survey IS NULL)
                    UNION ALL SELECT id, 3 FROM papers WHERE set_3_last_llm_is_offtopic = 0 AND (set_3_last_llm_is_survey = 0 OR set_3_last_llm_is_survey IS NULL)
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
        prompt_template = config.load_prompt_template(config.VERIFIER_TEMPLATE)
        model_alias = config.get_model_alias(config.LLM_SERVER_URL)
    except Exception as e:
        log(f"ERROR: Failed to load verifier template: {e}")
        return jsonify({'error': f'Failed to load verifier template: {e}'}), 500

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
                    SELECT id, 1 as set_num FROM papers WHERE set_1_last_llm_is_offtopic IS NOT NULL AND set_1_last_llm_is_offtopic != ''
                    UNION ALL SELECT id, 2 FROM papers WHERE set_2_last_llm_is_offtopic IS NOT NULL AND set_2_last_llm_is_offtopic != ''
                    UNION ALL SELECT id, 3 FROM papers WHERE set_3_last_llm_is_offtopic IS NOT NULL AND set_3_last_llm_is_offtopic != ''
                    ORDER BY id, set_num
                """)
            elif mode == 'remaining':
                cursor.execute("""
                    SELECT id, 1 as set_num FROM papers WHERE set_1_last_llm_is_offtopic IS NOT NULL AND set_1_last_llm_is_offtopic != '' AND (set_1_last_llm_verified IS NULL OR set_1_last_llm_verified = '')
                    UNION ALL SELECT id, 2 FROM papers WHERE set_2_last_llm_is_offtopic IS NOT NULL AND set_2_last_llm_is_offtopic != '' AND (set_2_last_llm_verified IS NULL OR set_2_last_llm_verified = '')
                    UNION ALL SELECT id, 3 FROM papers WHERE set_3_last_llm_is_offtopic IS NOT NULL AND set_3_last_llm_is_offtopic != '' AND (set_3_last_llm_verified IS NULL OR set_3_last_llm_verified = '')
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
        classify_template = config.load_prompt_template(config.PROMPT_TEMPLATE)
        verify_template = config.load_prompt_template(config.VERIFIER_TEMPLATE)
        reclassify_template = config.load_prompt_template(config.RECLASSIFY_PROMPT_TEMPLATE)
        model_alias = config.get_model_alias(config.LLM_SERVER_URL)
    except Exception as e:
        log(f"ERROR: Failed to load consensus templates: {e}", Colors.ERROR)
        return jsonify({'error': f'Failed to load consensus templates: {e}'}), 500

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
                SELECT id, 1 as set_num FROM papers WHERE (set_1_last_llm_verified IS NULL OR set_1_last_llm_estimated_score <= 7)
                UNION ALL SELECT id, 2 FROM papers WHERE (set_2_last_llm_verified IS NULL OR set_2_last_llm_estimated_score <= 7)
                UNION ALL SELECT id, 3 FROM papers WHERE (set_3_last_llm_verified IS NULL OR set_3_last_llm_estimated_score <= 7)
                ORDER BY id, set_num
            """)
            paper_set_pairs = cursor.fetchall()
        # --- DB CONNECTION RELEASED HERE ---

        log(f"{_color_prefix('DB QUERY:', Colors.DB)} mode={_color_mode(mode)} found {len(paper_set_pairs)} paper×set pairs")
        if not paper_set_pairs:
            log(f"WARNING: No paper×set pairs need consensus")
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
    
@queue_bp.app_errorhandler(404)
def not_found(e):
    log(f"{_color_prefix('ERROR:', Colors.ERROR)} Unknown endpoint {request.path}")
    return jsonify({'error': 'Not found'}), 404

@queue_bp.app_errorhandler(400)
def bad_request(e):
    log(f"{_color_prefix('ERROR:', Colors.ERROR)} Invalid JSON in request")
    return jsonify({'error': 'Invalid JSON'}), 400