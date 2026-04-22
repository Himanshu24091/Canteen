from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from database.models import get_db
from utils.auth import login_required
from utils.helpers import get_user_pending_amount
from utils.notifications import get_unread_notification_count
from utils.logger import log_event, BGREEN, BRED, BCYAN

user_bp = Blueprint('user', __name__)

@user_bp.route('/dashboard')
@login_required
def dashboard():
    user_id = session['user_id']
    db = get_db()

    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    pending_amt = get_user_pending_amount(user_id)

    today_orders = db.execute(
        "SELECT * FROM orders WHERE user_id = %s AND created_at::date = CURRENT_DATE ORDER BY created_at DESC",
        (user_id,)
    ).fetchall()

    recent_orders = db.execute(
        "SELECT * FROM orders WHERE user_id = %s ORDER BY created_at DESC LIMIT 5",
        (user_id,)
    ).fetchall()

    notif_count = get_unread_notification_count(user_id)
    db.close()

    return render_template('dashboard.html', user=user, pending_amt=pending_amt,
                           today_orders=today_orders, recent_orders=recent_orders,
                           notif_count=notif_count)

@user_bp.route('/menu')
@login_required
def menu():
    db = get_db()
    search = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip()

    query = "SELECT * FROM menu_items WHERE is_available = 1"
    params = []
    if search:
        query += " AND (name LIKE ? OR description LIKE ?)"
        params += [f'%{search}%', f'%{search}%']
    if category:
        query += " AND category = ?"
        params.append(category)
    query += " ORDER BY category, name"

    items = db.execute(query, params).fetchall()
    categories = db.execute("SELECT DISTINCT category FROM menu_items WHERE is_available = 1 ORDER BY category").fetchall()
    notif_count = get_unread_notification_count(session['user_id'])
    db.close()

    return render_template('menu.html', items=items, categories=categories,
                           search=search, selected_cat=category, notif_count=notif_count)

@user_bp.route('/cart')
@login_required
def cart():
    notif_count = get_unread_notification_count(session['user_id'])
    return render_template('cart.html', notif_count=notif_count)

@user_bp.route('/api/menu-item/<int:item_id>')
@login_required
def get_menu_item(item_id):
    db = get_db()
    item = db.execute("SELECT * FROM menu_items WHERE id = ? AND is_available = 1", (item_id,)).fetchone()
    db.close()
    if item:
        return jsonify({'id': item['id'], 'name': item['name'], 'price': item['price']})
    return jsonify({'error': 'Item not found'}), 404

@user_bp.route('/place-order', methods=['POST'])
@login_required
def place_order():
    data = request.get_json()
    items = data.get('items', [])
    notes = data.get('notes', '')

    if not items:
        return jsonify({'success': False, 'message': 'Cart is empty'}), 400

    db = get_db()
    try:
        total = 0
        validated = []
        for it in items:
            row = db.execute("SELECT * FROM menu_items WHERE id = ? AND is_available = 1", (it['id'],)).fetchone()
            if row:
                qty = max(1, int(it.get('qty', 1)))
                subtotal = row['price'] * qty
                total += subtotal
                validated.append({'id': row['id'], 'name': row['name'], 'price': row['price'], 'qty': qty})

        if not validated:
            return jsonify({'success': False, 'message': 'No valid items found'}), 400

        cur = db.execute(
            "INSERT INTO orders (user_id, total_amount, status, payment_status, notes) VALUES (%s, %s, 'pending', 'unpaid', %s) RETURNING id",
            (session['user_id'], round(total, 2), notes)
        )
        order_id = cur.fetchone()['id']

        for it in validated:
            db.execute(
                "INSERT INTO order_items (order_id, item_id, item_name, quantity, price) VALUES (?, ?, ?, ?, ?)",
                (order_id, it['id'], it['name'], it['qty'], it['price'])
            )

        db.commit()
        items_str = ', '.join(f"{i['name']} x{i['qty']}" for i in validated)
        log_event('🛒', 'ORDER PLACED', f"#{order_id}  {session['user_name']}  ₹{round(total,2)}  [{items_str}]", BGREEN)
        return jsonify({'success': True, 'order_id': order_id, 'total': round(total, 2)})
    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        db.close()

@user_bp.route('/history')
@login_required
def history():
    user_id = session['user_id']
    period = request.args.get('period', 'week')
    db = get_db()

    if period == 'day':
        date_filter = "o.created_at::date = CURRENT_DATE"
    elif period == 'month':
        date_filter = "o.created_at >= NOW() - INTERVAL '30 days'"
    else:
        date_filter = "o.created_at >= NOW() - INTERVAL '7 days'"

    orders = db.execute(
        f"""SELECT o.*,
               STRING_AGG(oi.item_name || ' x' || oi.quantity::text, ', ') as items_summary
            FROM orders o
            LEFT JOIN order_items oi ON o.id = oi.order_id
            WHERE o.user_id = %s AND {date_filter}
            GROUP BY o.id
            ORDER BY o.created_at DESC""",
        (user_id,)
    ).fetchall()

    total_spent = sum(o['total_amount'] for o in orders)
    notif_count = get_unread_notification_count(user_id)
    db.close()

    return render_template('history.html', orders=orders, period=period,
                           total_spent=total_spent, notif_count=notif_count)

@user_bp.route('/order/<int:order_id>')
@login_required
def order_detail(order_id):
    db = get_db()
    order = db.execute(
        "SELECT * FROM orders WHERE id = ? AND user_id = ?",
        (order_id, session['user_id'])
    ).fetchone()

    if not order:
        flash('Order not found.', 'danger')
        return redirect(url_for('user.history'))

    items = db.execute(
        "SELECT * FROM order_items WHERE order_id = ?", (order_id,)
    ).fetchall()
    notif_count = get_unread_notification_count(session['user_id'])
    db.close()

    return render_template('order_detail.html', order=order, items=items, notif_count=notif_count)

@user_bp.route('/notifications')
@login_required
def notifications():
    user_id = session['user_id']
    db = get_db()
    notifs = db.execute(
        """SELECT * FROM notifications
           WHERE (user_id = ? OR user_id IS NULL)
           ORDER BY created_at DESC LIMIT 50""",
        (user_id,)
    ).fetchall()

    db.execute(
        "UPDATE notifications SET is_read = 1 WHERE (user_id = ? OR user_id IS NULL) AND is_read = 0",
        (user_id,)
    )
    db.commit()
    db.close()

    return render_template('notifications.html', notifications=notifs, notif_count=0)

@user_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user_id = session['user_id']
    db = get_db()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        department = request.form.get('department', '').strip()
        db.execute("UPDATE users SET name=?, phone=?, department=? WHERE id=?",
                   (name, phone, department, user_id))
        db.commit()
        session['user_name'] = name
        log_event('✏', 'PROFILE UPDATE', f"{name} (id:{user_id})", BCYAN)
        flash('Profile updated!', 'success')
        return redirect(url_for('user.profile'))

    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    pending = get_user_pending_amount(user_id)
    notif_count = get_unread_notification_count(user_id)
    db.close()
    return render_template('profile.html', user=user, pending=pending, notif_count=notif_count)
