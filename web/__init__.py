# web/__init__.py
from flask import Flask
import logging
from . import filters
from .routes_ui import ui_bp
from .routes_data import data_bp
from .routes_files import files_bp

def create_web_app(db_path):
    app = Flask(__name__, template_folder='templates', static_folder='static')
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    
    # Register Jinja filters
    app.jinja_env.filters['render_status'] = filters.render_status_filter
    app.jinja_env.filters['render_verified_by'] = filters.render_verified_by_filter
    app.jinja_env.filters['render_changed_by'] = filters.render_changed_by_filter
    app.jinja_env.filters['bibtex'] = filters.bibtex_filter
    app.jinja_env.filters['get_json_path'] = filters.get_json_path_filter
    
    # Import db here to register the format_changed_timestamp filter
    from shared import db
    app.jinja_env.filters['format_changed_timestamp'] = db.format_changed_timestamp

    # Register Blueprints
    app.register_blueprint(ui_bp)
    app.register_blueprint(data_bp)
    app.register_blueprint(files_bp)

    return app