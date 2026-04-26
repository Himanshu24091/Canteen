from flask import Flask, render_template, session, g, request as flask_request
from config import Config
from database.init_db import init_db
from routes.auth_routes import auth_bp
from routes.user_routes import user_bp
from routes.admin_routes import admin_bp
from routes.group_routes import group_bp
from utils.logger import setup_logging, log_startup, log_request, log_event, log_separator
import os
import time

# Load .env file for local development
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.permanent_session_lifetime = __import__('datetime').timedelta(seconds=90 * 60)  # match idle timeout

    # Ensure upload directory exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Setup colored logging
    setup_logging()

    # Initialize database
    init_db()

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(group_bp)

    # ─── Idle Session Timeout ────────────────────────────────────
    IDLE_TIMEOUT_SECONDS = 60 * 60   # 1 hour idle = auto logout
    SKIP_TIMEOUT_PATHS = ('/static/', '/login', '/logout', '/register', '/', '/api/keep-alive')

    @app.before_request
    def before():
        import datetime
        g.start_time = time.time()

        # Skip for static files and auth pages
        path = flask_request.path
        if any(path.startswith(s) for s in SKIP_TIMEOUT_PATHS):
            return

        # Only apply to logged-in users
        if 'user_id' not in session:
            return

        # Check idle time
        last = session.get('last_activity')
        now = datetime.datetime.utcnow().timestamp()

        if last and (now - last) > IDLE_TIMEOUT_SECONDS:
            # Expired — wipe session and send back to login
            user_name = session.get('user_name', 'User')
            session.clear()
            from flask import flash, redirect, url_for
            flash(f'Session expired after inactivity. Please log in again.', 'warning')
            return redirect(url_for('auth.login'))

        # Refresh last_activity timestamp on every active request
        session['last_activity'] = now
        session.modified = True

    @app.after_request
    def after(response):
        # Skip static files to keep log clean
        path = flask_request.path
        if any(path.startswith(s) for s in ('/static/',)):
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

    # ─── Keep-alive (resets idle timer server-side) ───────────────
    @app.route('/api/keep-alive', methods=['POST'])
    def keep_alive():
        import datetime
        from flask import jsonify
        if 'user_id' in session:
            session['last_activity'] = datetime.datetime.utcnow().timestamp()
            session.modified = True
            return jsonify({'status': 'ok'})
        return jsonify({'status': 'not_logged_in'}), 401

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
