from database.models import get_db


def get_unread_notification_count(user_id):
    db = get_db()
    try:
        row = db.execute(
            "SELECT COUNT(*) as cnt FROM notifications WHERE user_id = %s AND is_read = 0",
            (user_id,)
        ).fetchone()
        return row['cnt'] if row else 0
    finally:
        db.close()


def send_notification(user_id, title, message, notif_type='info', link=None):
    """Send a notification to a single user."""
    db = get_db()
    try:
        db.execute(
            "INSERT INTO notifications (user_id, title, message, type, link) VALUES (%s, %s, %s, %s, %s)",
            (user_id, title, message, notif_type, link)
        )
        db.commit()
    finally:
        db.close()


def send_group_notification(db, group_id, title, message, notif_type='info',
                            link=None, exclude_user_id=None):
    """
    Send a notification to every member of a group (using an existing db connection).
    Optionally exclude one user (e.g. the actor who triggered the event).
    Does NOT commit — caller must commit.
    """
    members = db.execute(
        "SELECT user_id FROM group_members WHERE group_id = %s",
        (group_id,)
    ).fetchall()
    for m in members:
        if exclude_user_id and m['user_id'] == exclude_user_id:
            continue
        db.execute(
            "INSERT INTO notifications (user_id, title, message, type, link) VALUES (%s, %s, %s, %s, %s)",
            (m['user_id'], title, message, notif_type, link)
        )


def send_broadcast_notification(title, message, notif_type='info'):
    """Send notification to all users."""
    db = get_db()
    try:
        users = db.execute("SELECT id FROM users WHERE is_active = 1").fetchall()
        for u in users:
            db.execute(
                "INSERT INTO notifications (user_id, title, message, type) VALUES (%s, %s, %s, %s)",
                (u['id'], title, message, notif_type)
            )
        db.commit()
    finally:
        db.close()
