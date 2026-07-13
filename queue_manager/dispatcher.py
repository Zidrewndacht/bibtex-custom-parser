# queue/dispatcher.py
import json
import threading
import time
from shared import config
from .logging_utils import (
    log, log_file_dispatch, log_file_complete, log_file_error, 
    Colors, _color_prefix
)
from .state import (
    state, log_queue_status, 
    TASK_CLASSIFY, TASK_VERIFY, TASK_RECLASSIFY
)

def _send_to_vllm_sync(task):
    """Synchronous vLLM call (runs in background thread)."""
    task_id = task['task_id']
    task_type = task['task_type']
    paper_id = task['paper_id']
    set_num = task.get('set_num')
    prompt = task['prompt']
    model_alias = task.get('model_alias', 'default')
    state_machine = task.get('state_machine')
    
    log(f"{_color_prefix('SENDING:', Colors.VLLM_SEND)} task={task_id} type={task_type} paper={paper_id} set={set_num}")
    log_file_dispatch(task['task_id'], task['task_type'], task['paper_id'], task.get('set_num'))
        
    try:
        content, model_name, reasoning_trace = config.send_prompt_to_llm(
            prompt,
            server_url_base=config.LLM_SERVER_URL,
            model_name=model_alias,
            is_verification=(task_type == TASK_VERIFY)
        )
        
        success = content is not None
        llm_data = json.loads(content) if success and content else None
        
    except Exception as e:
        log(f"{_color_prefix('ERROR:', Colors.ERROR)} task={task_id} error={e}")
        log_file_error('vllm_call', e, task_id=task_id, paper_id=paper_id, set_num=set_num)
        success = False
        llm_data = None
        model_name = "error"
        reasoning_trace = str(e)
        content = ""
    
    # Decrement in-flight AFTER processing
    state.decrement_in_flight(task_type)
    
    # Invoke callback
    if state_machine:
        if hasattr(state_machine, 'on_set_complete'):
            state_machine.on_set_complete(set_num, success, llm_data, model_name, reasoning_trace or "", content or "")
        elif hasattr(state_machine, 'on_task_complete'):
            state_machine.on_task_complete(success, llm_data, model_name, reasoning_trace or "", content or "")
    
    log(f"{_color_prefix('COMPLETE:', Colors.VLLM_COMPLETE)} task={task_id} success={success}")
    log_file_complete(task_id, task_type, success, model_name if success else None, reasoning_trace if not success else None)

    log_queue_status()

def send_to_vllm(task):
    """Send task to vLLM asynchronously (fire-and-forget)."""
    thread = threading.Thread(target=_send_to_vllm_sync, args=(task,))
    thread.daemon = True
    thread.start()

def can_admit_task(task_type):
    """
    Homogeneous/mixed concurrency logic.
    """
    total = state.get_total_in_flight()
    task_in_flight = state.get_in_flight(task_type)
    
    if task_type == TASK_CLASSIFY:
        limit = config.MAX_CONCURRENT_WORKERS_CLASSIFY
    elif task_type == TASK_VERIFY:
        limit = config.MAX_CONCURRENT_WORKERS_VERIFY
    elif task_type == TASK_RECLASSIFY:
        limit = config.MAX_CONCURRENT_WORKERS_RECLASSIFY
    else:
        return False
    
    # Check if we're in homogeneous mode for this task type
    other_types_running = total - task_in_flight
    
    if other_types_running == 0:
        # Homogeneous mode - admit up to type-specific limit
        return task_in_flight < limit
    else:
        # Mixed mode - only admit if we're at or below minimum threshold
        return total < config.MIN_CONCURRENT_WORKERS

def dispatcher_loop():
    log(f"{_color_prefix('DISPATCHER:', Colors.DISPATCHER)} Starting dispatcher thread...")
    log_queue_status()
    
    while not state.is_shutdown():
        admitted_any = False
        
        # Drain queue as much as admission control allows
        while not state.is_shutdown():
            task = state.peek_queue()
            if task is None:
                break
            
            task_type = task.get('task_type')
            if not can_admit_task(task_type):
                break
            
            task = state.dequeue()
            if not task:
                break
            
            state.increment_in_flight(task_type)
            log(f"{_color_prefix('DISPATCH:', Colors.DISPATCHER)} task={task.get('task_id')} type={task_type}")
            log_queue_status()
            send_to_vllm(task)
            admitted_any = True
        
        if admitted_any:
            continue  # Immediately try to admit more
        
        # No work admitted - wait briefly before re-checking
        time.sleep(0.1)  # 100ms poll interval, lightweight yet fast enough.
    
    log(f"{_color_prefix('DISPATCHER:', Colors.DISPATCHER)} Shutdown complete.")