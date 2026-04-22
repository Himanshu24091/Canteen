from database.models import get_db

def get_user_pending_amount(user_id):
    db = get_db()
    try:
        row = db.execute(
            "SELECT COALESCE(SUM(total_amount), 0) as total FROM orders WHERE user_id = %s AND payment_status = 'unpaid'",
            (user_id,)
        ).fetchone()
        return round(float(row['total']), 2) if row else 0.0
    finally:
        db.close()

def get_order_summary(user_id, period='day'):
    db = get_db()
    try:
        if period == 'day':
            date_filter = "created_at::date = CURRENT_DATE"
        elif period == 'week':
            date_filter = "created_at >= NOW() - INTERVAL '7 days'"
        else:  # month
            date_filter = "created_at >= NOW() - INTERVAL '30 days'"

        rows = db.execute(
            f"SELECT * FROM orders WHERE user_id = %s AND {date_filter} ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()

def allowed_file(filename, allowed_extensions):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions
