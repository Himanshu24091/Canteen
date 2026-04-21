from database.models import get_db

def get_unread_notification_count(user_id):
    db = get_db()
    try:
        row = db.execute(
            "SELECT COUNT(*) as cnt FROM notifications WHERE (user_id = ? OR user_id IS NULL) AND is_read = 0",
            (user_id,)
        ).fetchone()
        return row['cnt'] if row else 0
    finally:
        db.close()

def send_notification(user_id, title, message, notif_type='info'):
    db = get_db()
    try:
        db.execute(
            "INSERT INTO notifications (user_id, title, message, type) VALUES (?, ?, ?, ?)",
            (user_id, title, message, notif_type)
        )
        db.commit()
    finally:
        db.close()

def send_broadcast_notification(title, message, notif_type='info'):
    """Send notification to all users (user_id = NULL means broadcast)"""
    db = get_db()
    try:
        db.execute(
            "INSERT INTO notifications (user_id, title, message, type) VALUES (NULL, ?, ?, ?)",
            (title, message, notif_type)
        )
        db.commit()
    finally:
        db.close()
