from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, make_response
from database.models import get_db
from utils.auth import admin_required
from utils.notifications import send_notification, send_broadcast_notification
from utils.logger import log_event, BGREEN, BRED, BCYAN, BYELLOW, BMAGENTA
from werkzeug.security import generate_password_hash
import csv
import io
from datetime import datetime

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/admin/dashboard')
@admin_required
def dashboard():
    db = get_db()
    total_users = db.execute("SELECT COUNT(*) as c FROM users WHERE role='user'").fetchone()['c']
    total_orders_today = db.execute(
        "SELECT COUNT(*) as c FROM orders WHERE date(created_at)=date('now','localtime')"
    ).fetchone()['c']
    revenue_today = db.execute(
        "SELECT COALESCE(SUM(total_amount),0) as r FROM orders WHERE date(created_at)=date('now','localtime') AND payment_status='paid'"
    ).fetchone()['r']
    total_pending = db.execute(
        "SELECT COALESCE(SUM(total_amount),0) as r FROM orders WHERE payment_status='unpaid'"
    ).fetchone()['r']
    recent_orders = db.execute(
        """SELECT o.*, u.name as user_name FROM orders o
           JOIN users u ON o.user_id = u.id
           ORDER BY o.created_at DESC LIMIT 10"""
    ).fetchall()
    popular_items = db.execute(
        """SELECT oi.item_name, SUM(oi.quantity) as total_qty, SUM(oi.quantity*oi.price) as revenue
           FROM order_items oi
           JOIN orders o ON oi.order_id = o.id
           WHERE o.created_at >= datetime('now','localtime','-30 days')
           GROUP BY oi.item_name ORDER BY total_qty DESC LIMIT 5"""
    ).fetchall()
    db.close()
    return render_template('admin/dashboard.html',
                           total_users=total_users,
                           total_orders_today=total_orders_today,
                           revenue_today=revenue_today,
                           total_pending=total_pending,
                           recent_orders=recent_orders,
                           popular_items=popular_items)

# ─── Menu Management ────────────────────────────────────────────────────────
@admin_bp.route('/admin/menu')
@admin_required
def manage_menu():
    db = get_db()
    items = db.execute("SELECT * FROM menu_items ORDER BY category, name").fetchall()
    db.close()
    return render_template('admin/menu.html', items=items)

@admin_bp.route('/admin/menu/add', methods=['GET', 'POST'])
@admin_required
def add_item():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        price = float(request.form.get('price', 0))
        category = request.form.get('category', 'General').strip()
        is_available = 1 if request.form.get('is_available') else 0

        db = get_db()
        db.execute(
            "INSERT INTO menu_items (name, description, price, category, is_available) VALUES (?,?,?,?,?)",
            (name, description, price, category, is_available)
        )
        db.commit()
        db.close()
        log_event('🍽', 'MENU ADD', f"{name}  ₹{price}  [{category}]", BGREEN)
        flash('Menu item added!', 'success')
        return redirect(url_for('admin.manage_menu'))
    return render_template('admin/add_edit_item.html', item=None)

@admin_bp.route('/admin/menu/edit/<int:item_id>', methods=['GET', 'POST'])
@admin_required
def edit_item(item_id):
    db = get_db()
    item = db.execute("SELECT * FROM menu_items WHERE id = ?", (item_id,)).fetchone()
    if not item:
        db.close()
        flash('Item not found.', 'danger')
        return redirect(url_for('admin.manage_menu'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        price = float(request.form.get('price', 0))
        category = request.form.get('category', 'General').strip()
        is_available = 1 if request.form.get('is_available') else 0

        db.execute(
            "UPDATE menu_items SET name=?, description=?, price=?, category=?, is_available=? WHERE id=?",
            (name, description, price, category, is_available, item_id)
        )
        db.commit()
        db.close()
        log_event('✏️', 'MENU EDIT', f"id:{item_id}  {name}  ₹{price}", BCYAN)
        flash('Item updated!', 'success')
        return redirect(url_for('admin.manage_menu'))

    db.close()
    return render_template('admin/add_edit_item.html', item=item)

@admin_bp.route('/admin/menu/delete/<int:item_id>', methods=['POST'])
@admin_required
def delete_item(item_id):
    db = get_db()
    db.execute("DELETE FROM menu_items WHERE id = ?", (item_id,))
    db.commit()
    db.close()
    log_event('🗑', 'MENU DELETE', f"id:{item_id}", BRED)
    flash('Item deleted.', 'info')
    return redirect(url_for('admin.manage_menu'))

@admin_bp.route('/admin/menu/toggle/<int:item_id>', methods=['POST'])
@admin_required
def toggle_item(item_id):
    db = get_db()
    item = db.execute("SELECT is_available FROM menu_items WHERE id = ?", (item_id,)).fetchone()
    if item:
        db.execute("UPDATE menu_items SET is_available = ? WHERE id = ?",
                   (0 if item['is_available'] else 1, item_id))
        db.commit()
    db.close()
    return redirect(url_for('admin.manage_menu'))

# ─── User Management ─────────────────────────────────────────────────────────
@admin_bp.route('/admin/users')
@admin_required
def manage_users():
    db = get_db()
    users = db.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    db.close()
    return render_template('admin/users.html', users=users)

@admin_bp.route('/admin/users/add', methods=['GET', 'POST'])
@admin_required
def add_user():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', 'user')
        phone = request.form.get('phone', '').strip()
        department = request.form.get('department', '').strip()

        db = get_db()
        existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            db.close()
            flash('Email already exists.', 'warning')
            return render_template('admin/add_user.html')

        db.execute(
            "INSERT INTO users (name, email, password, role, phone, department) VALUES (?,?,?,?,?,?)",
            (name, email, generate_password_hash(password), role, phone, department)
        )
        db.commit()
        db.close()
        log_event('👤', 'USER ADD', f"{name}  <{email}>  role:{role}", BGREEN)
        flash('User added!', 'success')
        return redirect(url_for('admin.manage_users'))
    return render_template('admin/add_user.html')

@admin_bp.route('/admin/users/toggle/<int:user_id>', methods=['POST'])
@admin_required
def toggle_user(user_id):
    db = get_db()
    user = db.execute("SELECT is_active FROM users WHERE id = ?", (user_id,)).fetchone()
    if user:
        db.execute("UPDATE users SET is_active = ? WHERE id = ?",
                   (0 if user['is_active'] else 1, user_id))
        db.commit()
    db.close()
    return redirect(url_for('admin.manage_users'))

@admin_bp.route('/admin/users/delete/<int:user_id>', methods=['POST'])
@admin_required
def delete_user(user_id):
    if user_id == session['user_id']:
        flash("You can't delete yourself.", 'danger')
        return redirect(url_for('admin.manage_users'))
    db = get_db()
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()
    db.close()
    log_event('🗑', 'USER DELETE', f"id:{user_id}", BRED)
    flash('User removed.', 'info')
    return redirect(url_for('admin.manage_users'))

# ─── Orders Management ───────────────────────────────────────────────────────
@admin_bp.route('/admin/orders')
@admin_required
def all_orders():
    db = get_db()
    status = request.args.get('status', '')
    payment = request.args.get('payment', '')

    query = """SELECT o.*, u.name as user_name FROM orders o
               JOIN users u ON o.user_id = u.id WHERE 1=1"""
    params = []
    if status:
        query += " AND o.status = ?"
        params.append(status)
    if payment:
        query += " AND o.payment_status = ?"
        params.append(payment)
    query += " ORDER BY o.created_at DESC"

    orders = db.execute(query, params).fetchall()
    db.close()
    return render_template('admin/orders.html', orders=orders, status=status, payment=payment)

@admin_bp.route('/admin/orders/<int:order_id>/status', methods=['POST'])
@admin_required
def update_order_status(order_id):
    new_status = request.form.get('status')
    db = get_db()
    db.execute("UPDATE orders SET status = ? WHERE id = ?", (new_status, order_id))
    db.commit()
    db.close()
    return redirect(url_for('admin.all_orders'))

@admin_bp.route('/admin/orders/<int:order_id>/payment', methods=['POST'])
@admin_required
def mark_payment(order_id):
    method = request.form.get('method', 'cash')
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order:
        db.execute("UPDATE orders SET payment_status='paid', payment_method=? WHERE id=?",
                   (method, order_id))
        db.execute(
            "INSERT INTO payments (user_id, order_id, amount, method, status) VALUES (?,?,?,?,'completed')",
            (order['user_id'], order_id, order['total_amount'], method)
        )
        db.commit()
        send_notification(order['user_id'], 'Payment Confirmed',
                          f'Your payment of ₹{order["total_amount"]:.2f} for Order #{order_id} has been received.', 'success')
        log_event('💰', 'PAYMENT', f"Order #{order_id}  ₹{order['total_amount']}  via {method}", BGREEN)
    db.close()
    flash('Payment marked as paid.', 'success')
    return redirect(url_for('admin.all_orders'))

# ─── Payments ────────────────────────────────────────────────────────────────
@admin_bp.route('/admin/payments')
@admin_required
def payments():
    db = get_db()
    payments = db.execute(
        """SELECT p.*, u.name as user_name, u.email as user_email
           FROM payments p JOIN users u ON p.user_id = u.id
           ORDER BY p.created_at DESC"""
    ).fetchall()
    db.close()
    return render_template('admin/payments.html', payments=payments)

# ─── Reminders ───────────────────────────────────────────────────────────────
@admin_bp.route('/admin/reminders', methods=['GET', 'POST'])
@admin_required
def send_reminders():
    db = get_db()
    if request.method == 'POST':
        target = request.form.get('target', 'all')
        message = request.form.get('message', '').strip()
        user_id_target = request.form.get('user_id')

        if target == 'all':
            # Send to all users with unpaid dues
            users_with_dues = db.execute(
                """SELECT DISTINCT user_id FROM orders WHERE payment_status='unpaid'"""
            ).fetchall()
            for u in users_with_dues:
                send_notification(u['user_id'], '⚠️ Payment Reminder', message, 'warning')
            flash(f'Reminder sent to {len(users_with_dues)} users.', 'success')
        elif target == 'broadcast':
            send_broadcast_notification('📢 Announcement', message, 'info')
            flash('Broadcast sent to all users.', 'success')
        elif target == 'specific' and user_id_target:
            send_notification(int(user_id_target), '⚠️ Payment Reminder', message, 'warning')
            flash('Reminder sent.', 'success')

        db.close()
        return redirect(url_for('admin.send_reminders'))

    users = db.execute(
        """SELECT u.id, u.name, u.email, COALESCE(SUM(o.total_amount),0) as pending
           FROM users u
           LEFT JOIN orders o ON u.id=o.user_id AND o.payment_status='unpaid'
           WHERE u.role='user'
           GROUP BY u.id HAVING pending > 0
           ORDER BY pending DESC"""
    ).fetchall()
    db.close()
    return render_template('admin/reminders.html', users=users)

# ─── Reports ─────────────────────────────────────────────────────────────────
@admin_bp.route('/admin/reports')
@admin_required
def reports():
    db = get_db()
    period = request.args.get('period', 'week')
    if period == 'day':
        date_filter = "date(o.created_at) = date('now','localtime')"
    elif period == 'month':
        date_filter = "o.created_at >= datetime('now','localtime','-30 days')"
    else:
        date_filter = "o.created_at >= datetime('now','localtime','-7 days')"

    summary = db.execute(
        f"""SELECT COUNT(*) as total_orders, COALESCE(SUM(total_amount),0) as total_revenue,
               COALESCE(SUM(CASE WHEN payment_status='paid' THEN total_amount END),0) as collected,
               COALESCE(SUM(CASE WHEN payment_status='unpaid' THEN total_amount END),0) as pending
            FROM orders o WHERE {date_filter}"""
    ).fetchone()

    top_users = db.execute(
        f"""SELECT u.name, u.email, COUNT(o.id) as order_count, SUM(o.total_amount) as spent
            FROM orders o JOIN users u ON o.user_id=u.id
            WHERE {date_filter} GROUP BY u.id ORDER BY spent DESC LIMIT 10"""
    ).fetchall()

    daily_revenue = db.execute(
        """SELECT date(created_at) as day, SUM(total_amount) as revenue, COUNT(*) as orders
           FROM orders WHERE created_at >= datetime('now','localtime','-30 days')
           GROUP BY day ORDER BY day"""
    ).fetchall()

    db.close()
    return render_template('admin/reports.html', summary=summary, top_users=top_users,
                           daily_revenue=daily_revenue, period=period)

@admin_bp.route('/admin/reports/export')
@admin_required
def export_orders():
    db = get_db()
    orders = db.execute(
        """SELECT o.id, u.name, u.email, o.total_amount, o.status, o.payment_status,
                  o.payment_method, o.created_at
           FROM orders o JOIN users u ON o.user_id=u.id
           ORDER BY o.created_at DESC"""
    ).fetchall()
    db.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Order ID', 'Customer', 'Email', 'Amount', 'Status', 'Payment Status', 'Payment Method', 'Date'])
    for o in orders:
        writer.writerow([o['id'], o['name'], o['email'], o['total_amount'],
                         o['status'], o['payment_status'], o['payment_method'], o['created_at']])

    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = f'attachment; filename=orders_{datetime.now().strftime("%Y%m%d")}.csv'
    response.headers['Content-type'] = 'text/csv'
    return response
