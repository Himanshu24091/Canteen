from flask import Flask, render_template, session, g, request as flask_request
from config import Config
from database.init_db import init_db
from routes.auth_routes import auth_bp
from routes.user_routes import user_bp
from routes.admin_routes import admin_bp
from utils.logger import setup_logging, log_startup, log_request, log_event, log_separator
import os
import time

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.permanent_session_lifetime = __import__('datetime').timedelta(days=7)

    # Ensure required directories exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(os.path.dirname(app.config['DATABASE_PATH']), exist_ok=True)

    # Setup colored logging
    setup_logging()

    # Initialize database
    init_db()

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(admin_bp)

    # ─── Activity Logging Hooks ──────────────────────────────────
    SKIP_PATHS = ('/static/',)

    @app.before_request
    def before():
        g.start_time = time.time()

    @app.after_request
    def after(response):
        # Skip static files to keep log clean
        path = flask_request.path
        if any(path.startswith(s) for s in SKIP_PATHS):
            return response

        duration = (time.time() - g.start_time) * 1000
        user = None
        if 'user_name' in session:
            role = session.get('role', 'user')
            user = f"{session['user_name']} ({role})"

        log_request(
            method=flask_request.method,
            path=path,
            status=response.status_code,
            duration_ms=duration,
            user=user,
        )
        return response

    # ─── Home route ───────────────────────────────────────────────
    @app.route('/')
    def index():
        return render_template('index.html')

    # ─── Context processor for nav ────────────────────────────────
    @app.context_processor
    def inject_globals():
        from utils.notifications import get_unread_notification_count
        notif_count = 0
        if 'user_id' in session:
            notif_count = get_unread_notification_count(session['user_id'])
        return dict(notif_count=notif_count, session=session)

    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template('errors/500.html'), 500

    return app

app = create_app()

if __name__ == '__main__':
    is_prod = os.environ.get('FLASK_ENV') == 'production'
    port = int(os.environ.get('PORT', 5000))
    if not is_prod:
        log_startup('127.0.0.1', port)
    app.run(debug=not is_prod, port=port, host='0.0.0.0')
