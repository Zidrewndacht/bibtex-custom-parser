# run_queue.py
import os
import sys
import signal
import threading
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shared import config
from queue_manager import create_queue_app
from queue_manager.dispatcher import dispatcher_loop
from queue_manager.logging_utils import log, Colors, _color_prefix, _log_to_file

def main():
    parser = argparse.ArgumentParser(description="Research Parça - Queue Manager")
    parser.add_argument('--db', default=config.DATABASE_FILE, help='Path to SQLite database')
    args = parser.parse_args()

    db_path = os.path.abspath(args.db)
    config.DATABASE_FILE = db_path

    def signal_handler(sig, frame):
        _log_to_file('dispatcher.log', event='shutdown', signal=sig)
        print("\n[SHUTDOWN] Received shutdown signal...")
        sys.exit(1)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    app = create_queue_app(db_path)
    
    _log_to_file('dispatcher.log', event='startup', llm_server=config.LLM_SERVER_URL, http_api=f"{config.QUEUE_MANAGER_HOST}:{config.QUEUE_MANAGER_PORT}")
    
    log(f"{_color_prefix('STARTUP:', Colors.DISPATCHER)} {'=' * 52}")
    log(f"{_color_prefix('STARTUP:', Colors.DISPATCHER)} ResearchParça Queue Manager Starting")
    log(f"{_color_prefix('STARTUP:', Colors.DISPATCHER)} {'=' * 52}")
    log(f"vLLM Server: {config.LLM_SERVER_URL}")
    log(f"HTTP API: http://{config.QUEUE_MANAGER_HOST}:{config.QUEUE_MANAGER_PORT}")
    log(f"Concurrency Limits: classify={config.MAX_CONCURRENT_WORKERS_CLASSIFY} verify={config.MAX_CONCURRENT_WORKERS_VERIFY} reclassify={config.MAX_CONCURRENT_WORKERS_RECLASSIFY} mixed_threshold={config.MIN_CONCURRENT_WORKERS}")
    log("=" * 60)

    dispatcher_thread = threading.Thread(target=dispatcher_loop, daemon=True)
    dispatcher_thread.start()

    try:
        app.run(
            host=config.QUEUE_MANAGER_HOST,
            port=config.QUEUE_MANAGER_PORT,
            threaded=True,
            debug=False
        )
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    main()