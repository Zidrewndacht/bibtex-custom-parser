# browse_db.py
import os
import sys
import argparse
import threading
import webbrowser
import time
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
    
    # Use the configured frontend port
    web_port = config.FRONTEND_PORT 
    print(f"[Web] Starting Web UI on http://localhost:{web_port}")
    
    # # Standard Werkzeug reloader check to prevent double browser opens - this doesn't seem to be working, still opens twice.
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        threading.Thread(target=open_browser, args=(web_port,), daemon=True).start()
    elif not os.environ.get('WERKZEUG_RUN_MAIN'):
        threading.Thread(target=open_browser, args=(web_port,), daemon=True).start()
        
    app = create_web_app(db_path)
    app.run(host='0.0.0.0', port=web_port, debug=False, threaded=True)

if __name__ == '__main__':
    main()