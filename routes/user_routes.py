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

    # ── Period summaries (daily / weekly / monthly totals) ──
    summary = db.execute("""
        SELECT
          COALESCE(SUM(CASE WHEN created_at::date = CURRENT_DATE THEN total_amount END), 0)             AS day_total,
          COALESCE(SUM(CASE WHEN created_at >= NOW() - INTERVAL '7 days'  THEN total_amount END), 0)   AS week_total,
          COALESCE(SUM(CASE WHEN created_at >= NOW() - INTERVAL '30 days' THEN total_amount END), 0)   AS month_total,
          COUNT(CASE WHEN created_at::date = CURRENT_DATE THEN 1 END)                                   AS day_count,
          COUNT(CASE WHEN created_at >= NOW() - INTERVAL '7 days'  THEN 1 END)                         AS week_count,
          COUNT(CASE WHEN created_at >= NOW() - INTERVAL '30 days' THEN 1 END)                         AS month_count
        FROM orders WHERE user_id = %s
    """, (user_id,)).fetchone()

    # ── Chart data: last 30 days daily spend ──
    chart_rows = db.execute("""
        SELECT created_at::date AS day,
               COALESCE(SUM(total_amount), 0) AS spent,
               COUNT(*) AS orders
        FROM orders
        WHERE user_id = %s AND created_at >= NOW() - INTERVAL '30 days'
        GROUP BY day ORDER BY day
    """, (user_id,)).fetchall()

    chart_labels  = [r['day'] for r in chart_rows]
    chart_spent   = [float(r['spent']) for r in chart_rows]

    # ── Weekly aggregation for weekly chart (last 4 weeks) ──
    week_rows = db.execute("""
        SELECT DATE_TRUNC('week', created_at)::date AS week_start,
               COALESCE(SUM(total_amount), 0) AS spent
        FROM orders
        WHERE user_id = %s AND created_at >= NOW() - INTERVAL '28 days'
        GROUP BY week_start ORDER BY week_start
    """, (user_id,)).fetchall()

    week_labels = [f"Week of {r['week_start']}" for r in week_rows]
    week_spent  = [float(r['spent']) for r in week_rows]

    total_spent = sum(o['total_amount'] for o in orders)
    notif_count = get_unread_notification_count(user_id)
    db.close()

    return render_template('history.html', orders=orders, period=period,
                           total_spent=total_spent, summary=summary,
                           chart_labels=chart_labels, chart_spent=chart_spent,
                           week_labels=week_labels, week_spent=week_spent,
                           notif_count=notif_count)

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
           WHERE user_id = %s
           ORDER BY created_at DESC LIMIT 60""",
        (user_id,)
    ).fetchall()

    db.execute(
        "UPDATE notifications SET is_read = 1 WHERE user_id = %s AND is_read = 0",
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


@user_bp.route('/api/users-list')
@login_required
def users_list_api():
    """Return active non-admin users. Admins only see all users."""
    db = get_db()
    is_admin_req = session.get('role') == 'admin'
    if is_admin_req:
        users = db.execute(
            "SELECT id, name, email FROM users WHERE is_active = 1 ORDER BY name"
        ).fetchall()
    else:
        # Normal users cannot see admin accounts at all
        users = db.execute(
            "SELECT id, name, email FROM users WHERE is_active = 1 AND role != 'admin' ORDER BY name"
        ).fetchall()
    db.close()
    return jsonify({'users': users})


@user_bp.route('/api/search-users')
@login_required
def search_users():
    """
    Privacy-safe user search: never returns full list, only matches.
    Normal users cannot find admin accounts.
    Excludes current user and already-existing group members.
    Searchable by: name, email prefix, or exact numeric user ID.
    """
    q = request.args.get('q', '').strip()
    group_id = request.args.get('group_id', type=int)

    # Require at least 1 character — prevents "dump everything" calls
    if not q:
        return jsonify({'users': []})

    db = get_db()
    is_admin_req = session.get('role') == 'admin'
    current_user_id = session['user_id']

    params = []

    # Try numeric ID exact match
    id_match = None
    try:
        id_match = int(q)
    except (ValueError, TypeError):
        pass

    if id_match is not None:
        sql = """
            SELECT id, name, email, department, role
            FROM users
            WHERE is_active = 1
              AND (name ILIKE %s OR email ILIKE %s OR id = %s)
        """
        params = [f'%{q}%', f'%{q}%', id_match]
    else:
        sql = """
            SELECT id, name, email, department, role
            FROM users
            WHERE is_active = 1
              AND (name ILIKE %s OR email ILIKE %s)
        """
        params = [f'%{q}%', f'%{q}%']

    # Normal users must not see admin accounts
    if not is_admin_req:
        sql += " AND role != 'admin'"

    # Never show the current user to themselves
    sql += " AND id != %s"
    params.append(current_user_id)

    sql += " ORDER BY name LIMIT 10"

    users = db.execute(sql, params).fetchall()

    # Exclude existing group members (if group context provided)
    if group_id:
        existing = db.execute(
            "SELECT user_id FROM group_members WHERE group_id = %s", (group_id,)
        ).fetchall()
        existing_ids = {r['user_id'] for r in existing}
        users = [u for u in users if u['id'] not in existing_ids]

    db.close()

    # Return only safe, non-sensitive fields
    return jsonify({'users': [
        {
            'id': u['id'],
            'name': u['name'],
            'email': u['email'],
            'department': u.get('department') or ''
        }
        for u in users
    ]})


