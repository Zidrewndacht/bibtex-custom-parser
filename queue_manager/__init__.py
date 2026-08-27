# queue/__init__.py
import logging

from flask import Flask

from shared import db

from .routes import queue_bp


def create_queue_app(db_path):
    app = Flask(__name__)
    app.config['JSON_SORT_KEYS'] = False  # Preserve key order in responses
    
    # Disable Flask's default logging to match original behavior
    werkzeug_log = logging.getLogger('werkzeug')
    werkzeug_log.setLevel(logging.ERROR)
    
    app.register_blueprint(queue_bp)
    
    # Initialize DB
    db.init_db(db_path)
    
    return app