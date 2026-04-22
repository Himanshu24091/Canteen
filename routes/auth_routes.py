from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from database.models import get_db
from utils.logger import log_event, log_separator, BGREEN, BRED, BCYAN, BYELLOW

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('user.dashboard') if session.get('role') == 'user' else url_for('admin.dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email = ? AND is_active = 1", (email,)).fetchone()
        db.close()

        if user and check_password_hash(user['password'], password):
            session.clear()
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            session['role'] = user['role']
            session.permanent = True
            log_separator()
            log_event('🔑', 'LOGIN', f"{user['name']} ({user['role']})  <{email}>", BGREEN)
            if user['role'] == 'admin':
                return redirect(url_for('admin.dashboard'))
            return redirect(url_for('user.dashboard'))

        log_event('⚠', 'LOGIN FAILED', f"Bad credentials for <{email}>", BRED)
        flash('Invalid email or password.', 'danger')

    return render_template('login.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('user.dashboard'))

    if request.method == 'POST':
        name       = request.form.get('name', '').strip()
        email      = request.form.get('email', '').strip()
        password   = request.form.get('password', '')
        confirm    = request.form.get('confirm_password', '')
        phone      = request.form.get('phone', '').strip()
        department = request.form.get('department', '').strip()

        if not all([name, email, password]):
            flash('Please fill in all required fields.', 'danger')
            return render_template('signup.html')

        if password != confirm:
            flash('Passwords do not match.', 'danger')
            return render_template('signup.html')

        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return render_template('signup.html')

        db = get_db()
        existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            db.close()
            flash('Email already registered. Please login.', 'warning')
            return redirect(url_for('auth.login'))

        db.execute(
            "INSERT INTO users (name, email, password, phone, department) VALUES (?, ?, ?, ?, ?)",
            (name, email, generate_password_hash(password), phone, department)
        )
        db.commit()
        db.close()
        log_event('👤', 'NEW USER', f"{name}  <{email}>  dept:{department}", BCYAN)
        flash('Account created successfully! Please login.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('signup.html')

@auth_bp.route('/logout')
def logout():
    name = session.get('user_name', 'Unknown')
    reason = request.args.get('reason', '')
    log_event('🚪', 'LOGOUT', f"{name}{' (idle timeout)' if reason == 'idle' else ''}", BYELLOW)
    log_separator()
    session.clear()
    if reason == 'idle':
        flash('You were logged out due to inactivity.', 'warning')
    else:
        flash('You have been logged out.', 'info')
    return redirect(url_for('index'))
