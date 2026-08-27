# browse_db.py
import argparse
import os
import sys
import threading
import time
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shared import config, db
from web import create_web_app


def open_browser(port):
    time.sleep(1.5)
    webbrowser.open(f'http://localhost:{port}')

def main():
    parser = argparse.ArgumentParser(description="ResearchParsa - Web UI")
    parser.add_argument('--db', default=config.DATABASE_FILE, help='Path to SQLite database')
    args = parser.parse_args()
    
    db_path = os.path.abspath(args.db)
    config.DATABASE_FILE = db_path
    db.init_db(db_path)
    print(f"[Init] Database ready: {db_path}")
    
    web_port = config.FRONTEND_PORT 
    app = create_web_app(db_path)
    
    if config.DEBUG_MODE:
        print(f"[Web] Starting Flask Dev Server (DEBUG) on http://{config.FRONTEND_HOST}:{web_port}")
        
        use_reloader = True
        # WERKZEUG_RUN_MAIN is 'true' ONLY in the child process that actually serves requests.
        # This prevents the browser from opening twice (once in parent, once in child).
        if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not use_reloader:
            threading.Thread(target=open_browser, args=(web_port,), daemon=True).start()
            
        app.run(
            host=config.FRONTEND_HOST, 
            port=web_port, 
            debug=True, 
            threaded=True,
            use_reloader=use_reloader
        )
    else:
        from waitress import serve
        print(f"[Web] Starting on http://{config.FRONTEND_HOST}:{web_port}")
        
        threading.Thread(target=open_browser, args=(web_port,), daemon=True).start()
        
        serve(
            app,
            host=config.FRONTEND_HOST,
            port=web_port,
            threads=config.FRONTEND_WAITRESS_THREADS,
            channel_timeout=7200
        )

if __name__ == '__main__':
    main()