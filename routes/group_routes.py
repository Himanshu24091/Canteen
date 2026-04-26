from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, current_app
from database.models import get_db
from utils.auth import login_required, admin_required
from utils.logger import log_event, BGREEN, BCYAN, BYELLOW
from utils.notifications import send_group_notification
import os
from werkzeug.utils import secure_filename

group_bp = Blueprint('group', __name__, url_prefix='/groups')

ALLOWED_PROOF_EXT = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf'}

def _allowed_proof(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_PROOF_EXT



# ─── Helper: post system message ──────────────────────────────────────────────
def _post_system_message(db, group_id, text):
    db.execute(
        "INSERT INTO messages (group_id, sender_id, message, type) VALUES (%s, NULL, %s, 'system')",
        (group_id, text)
    )


# ─── Helper: is member / admin ────────────────────────────────────────────────
def _get_membership(db, group_id, user_id):
    """Returns the member row or None."""
    return db.execute(
        "SELECT * FROM group_members WHERE group_id = %s AND user_id = %s",
        (group_id, user_id)
    ).fetchone()


def _require_membership(db, group_id, user_id):
    """Return membership row, or a synthetic admin row, or None (with flash)."""
    m = _get_membership(db, group_id, user_id)
    if m:
        return m
    # Site admins can access any group even if not a member
    if session.get('role') == 'admin':
        # Return a synthetic membership so downstream code works
        return {'group_id': group_id, 'user_id': user_id, 'role': 'admin'}
    flash('You are not a member of this group.', 'danger')
    return None


# ══════════════════════════════════════════════════════════════════════════════
# GROUP LIST / MY GROUPS
# ══════════════════════════════════════════════════════════════════════════════
@group_bp.route('/')
@login_required
def list_groups():
    db = get_db()
    user_id = session['user_id']
    groups = db.execute("""
        SELECT g.*, u.name AS creator_name,
               COUNT(gm2.id) AS member_count
        FROM groups g
        JOIN group_members gm ON gm.group_id = g.id AND gm.user_id = %s
        JOIN users u ON u.id = g.created_by
        LEFT JOIN group_members gm2 ON gm2.group_id = g.id
        GROUP BY g.id, u.name
        ORDER BY g.created_at DESC
    """, (user_id,)).fetchall()
    db.close()
    return render_template('groups/list.html', groups=groups)


# ══════════════════════════════════════════════════════════════════════════════
# CREATE GROUP
# ══════════════════════════════════════════════════════════════════════════════
@group_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_group():
    db = get_db()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        user_id = session['user_id']

        if not name:
            flash('Group name is required.', 'danger')
            db.close()
            return render_template('groups/create.html')

        # Insert group
        cur = db.execute(
            "INSERT INTO groups (name, description, created_by) VALUES (%s, %s, %s) RETURNING id",
            (name, description, user_id)
        )
        group_id = cur.fetchone()['id']

        # Add creator as admin member
        db.execute(
            "INSERT INTO group_members (group_id, user_id, role) VALUES (%s, %s, 'admin')",
            (group_id, user_id)
        )

        # System message
        _post_system_message(db, group_id, f"Group '{name}' was created by {session['user_name']}.")

        db.commit()
        db.close()
        log_event('👥', 'GROUP CREATED', f"{name} by {session['user_name']}", BCYAN)
        flash(f"Group '{name}' created successfully!", 'success')
        return redirect(url_for('group.dashboard', group_id=group_id))

    # All users for member pre-selection
    users = db.execute(
        "SELECT id, name, email FROM users WHERE is_active = 1 AND id != %s ORDER BY name",
        (session['user_id'],)
    ).fetchall()
    db.close()
    return render_template('groups/create.html', users=users)


# ══════════════════════════════════════════════════════════════════════════════
# GROUP DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
@group_bp.route('/<int:group_id>')
@login_required
def dashboard(group_id):
    db = get_db()
    user_id = session['user_id']

    group = db.execute("SELECT * FROM groups WHERE id = %s", (group_id,)).fetchone()
    if not group:
        flash('Group not found.', 'danger')
        db.close()
        return redirect(url_for('group.list_groups'))

    membership = _require_membership(db, group_id, user_id)
    if not membership:
        db.close()
        return redirect(url_for('group.list_groups'))

    members = db.execute("""
        SELECT gm.*, u.name, u.email, u.department
        FROM group_members gm JOIN users u ON u.id = gm.user_id
        WHERE gm.group_id = %s ORDER BY gm.role DESC, u.name
    """, (group_id,)).fetchall()

    # Recent expenses
    expenses = db.execute("""
        SELECT e.*, u.name AS paid_by_name
        FROM expenses e JOIN users u ON u.id = e.paid_by
        WHERE e.group_id = %s ORDER BY e.created_at DESC LIMIT 10
    """, (group_id,)).fetchall()

    # Balance summary: what the current user owes / is owed
    # Amount current user owes to each person
    owed_rows = db.execute("""
        SELECT u.name AS creditor_name, u.id AS creditor_id,
               COALESCE(SUM(ep.amount_owed), 0) AS total_owed
        FROM expense_participants ep
        JOIN expenses e ON e.id = ep.expense_id
        JOIN users u ON u.id = e.paid_by
        WHERE ep.user_id = %s AND e.group_id = %s AND e.paid_by != %s
        GROUP BY u.id, u.name
    """, (user_id, group_id, user_id)).fetchall()

    # Amount others owe to current user (current user paid)
    receivable_rows = db.execute("""
        SELECT u.name AS debtor_name, u.id AS debtor_id,
               COALESCE(SUM(ep.amount_owed), 0) AS total_owed
        FROM expense_participants ep
        JOIN expenses e ON e.id = ep.expense_id
        JOIN users u ON u.id = ep.user_id
        WHERE e.paid_by = %s AND ep.user_id != %s AND e.group_id = %s
        GROUP BY u.id, u.name
    """, (user_id, user_id, group_id)).fetchall()

    # Subtract settled amounts from owed
    settled_paid = db.execute("""
        SELECT to_user, COALESCE(SUM(amount), 0) AS settled
        FROM settlements
        WHERE from_user = %s AND group_id = %s AND status = 'settled'
        GROUP BY to_user
    """, (user_id, group_id)).fetchall()
    settled_paid_map = {r['to_user']: r['settled'] for r in settled_paid}

    settled_recv = db.execute("""
        SELECT from_user, COALESCE(SUM(amount), 0) AS settled
        FROM settlements
        WHERE to_user = %s AND group_id = %s AND status = 'settled'
        GROUP BY from_user
    """, (user_id, group_id)).fetchall()
    settled_recv_map = {r['from_user']: r['settled'] for r in settled_recv}

    balances = []
    for r in owed_rows:
        net = max(0, r['total_owed'] - settled_paid_map.get(r['creditor_id'], 0))
        if net > 0.005:
            balances.append({'person': r['creditor_name'], 'person_id': r['creditor_id'],
                             'amount': round(net, 2), 'direction': 'owe'})

    for r in receivable_rows:
        net = max(0, r['total_owed'] - settled_recv_map.get(r['debtor_id'], 0))
        if net > 0.005:
            balances.append({'person': r['debtor_name'], 'person_id': r['debtor_id'],
                             'amount': round(net, 2), 'direction': 'receive'})

    db.close()
    return render_template('groups/dashboard.html',
                           group=group, membership=membership,
                           members=members, expenses=expenses,
                           balances=balances)


# ══════════════════════════════════════════════════════════════════════════════
# ADD MEMBER
# ══════════════════════════════════════════════════════════════════════════════
@group_bp.route('/<int:group_id>/add-member', methods=['POST'])
@login_required
def add_member(group_id):
    db = get_db()
    user_id = session['user_id']
    m = _require_membership(db, group_id, user_id)
    if not m or m['role'] != 'admin':
        db.close()
        flash('Only group admins can add members.', 'danger')
        return redirect(url_for('group.dashboard', group_id=group_id))

    new_user_id = request.form.get('user_id', type=int)
    role = request.form.get('role', 'member')

    if not new_user_id:
        flash('Please select a user.', 'danger')
        db.close()
        return redirect(url_for('group.dashboard', group_id=group_id))

    existing = _get_membership(db, group_id, new_user_id)
    if existing:
        flash('User is already a member.', 'warning')
        db.close()
        return redirect(url_for('group.dashboard', group_id=group_id))

    new_user = db.execute("SELECT name FROM users WHERE id = %s", (new_user_id,)).fetchone()
    if not new_user:
        flash('User not found.', 'danger')
        db.close()
        return redirect(url_for('group.dashboard', group_id=group_id))

    db.execute(
        "INSERT INTO group_members (group_id, user_id, role) VALUES (%s, %s, %s)",
        (group_id, new_user_id, role)
    )
    _post_system_message(db, group_id, f"{new_user['name']} was added to the group by {session['user_name']}.")
    db.commit()
    db.close()
    flash(f"{new_user['name']} added to group!", 'success')
    return redirect(url_for('group.dashboard', group_id=group_id))


# ══════════════════════════════════════════════════════════════════════════════
# REMOVE MEMBER
# ══════════════════════════════════════════════════════════════════════════════
@group_bp.route('/<int:group_id>/remove-member/<int:target_user_id>', methods=['POST'])
@login_required
def remove_member(group_id, target_user_id):
    db = get_db()
    user_id = session['user_id']
    m = _require_membership(db, group_id, user_id)
    if not m or m['role'] != 'admin':
        db.close()
        flash('Only group admins can remove members.', 'danger')
        return redirect(url_for('group.dashboard', group_id=group_id))

    if target_user_id == user_id:
        flash('You cannot remove yourself from the group.', 'warning')
        db.close()
        return redirect(url_for('group.dashboard', group_id=group_id))

    target = db.execute("SELECT name FROM users WHERE id = %s", (target_user_id,)).fetchone()
    db.execute(
        "DELETE FROM group_members WHERE group_id = %s AND user_id = %s",
        (group_id, target_user_id)
    )
    if target:
        _post_system_message(db, group_id, f"{target['name']} was removed from the group.")
    db.commit()
    db.close()
    flash('Member removed.', 'success')
    return redirect(url_for('group.dashboard', group_id=group_id))


# ══════════════════════════════════════════════════════════════════════════════
# BATCH ADD MEMBERS (AJAX – multi-select search UI)
# ══════════════════════════════════════════════════════════════════════════════
@group_bp.route('/<int:group_id>/add-members', methods=['POST'])
@login_required
def add_members_batch(group_id):
    """
    Accepts JSON: { "user_ids": [1, 2, 3], "role": "member" }
    Adds multiple users at once; skips duplicates and invalid IDs.
    Normal users cannot add admin accounts.
    """
    db = get_db()
    user_id = session['user_id']
    m = _require_membership(db, group_id, user_id)
    if not m or m['role'] != 'admin':
        db.close()
        return jsonify({'success': False, 'error': 'Only group admins can add members.'}), 403

    data = request.get_json(silent=True) or {}
    new_user_ids = data.get('user_ids', [])
    role = data.get('role', 'member')

    if not new_user_ids:
        db.close()
        return jsonify({'success': False, 'error': 'No users selected.'}), 400

    is_admin_req = session.get('role') == 'admin'
    added = []
    skipped = []

    for new_uid in new_user_ids:
        # Skip if already a member
        if _get_membership(db, group_id, new_uid):
            skipped.append(new_uid)
            continue

        # Verify user exists and is active; block admin accounts for normal users
        if is_admin_req:
            new_user = db.execute(
                "SELECT name FROM users WHERE id = %s AND is_active = 1", (new_uid,)
            ).fetchone()
        else:
            # Normal users CANNOT add admin accounts to groups
            new_user = db.execute(
                "SELECT name FROM users WHERE id = %s AND is_active = 1 AND role != 'admin'",
                (new_uid,)
            ).fetchone()

        if not new_user:
            skipped.append(new_uid)
            continue

        db.execute(
            "INSERT INTO group_members (group_id, user_id, role) VALUES (%s, %s, %s)",
            (group_id, new_uid, role)
        )
        added.append(new_user['name'])

    if added:
        names_str = ', '.join(added)
        verb = 'was' if len(added) == 1 else 'were'
        _post_system_message(db, group_id,
            f"👤 {names_str} {verb} added to the group by {session['user_name']}.")
        db.commit()
        log_event('👤', 'MEMBERS ADDED', f"Group:{group_id}  +{len(added)} users", BCYAN)
    else:
        db.rollback()

    db.close()

    if added:
        return jsonify({'success': True, 'added': added, 'count': len(added)})
    else:
        return jsonify({'success': False, 'error': 'No valid new users to add (already members or not found).'}), 400


# ══════════════════════════════════════════════════════════════════════════════
# ADD EXPENSE
# ══════════════════════════════════════════════════════════════════════════════
@group_bp.route('/<int:group_id>/add-expense', methods=['GET', 'POST'])
@login_required
def add_expense(group_id):
    db = get_db()
    user_id = session['user_id']

    group = db.execute("SELECT * FROM groups WHERE id = %s", (group_id,)).fetchone()
    if not group:
        flash('Group not found.', 'danger')
        db.close()
        return redirect(url_for('group.list_groups'))

    membership = _require_membership(db, group_id, user_id)
    if not membership:
        db.close()
        return redirect(url_for('group.list_groups'))

    members = db.execute("""
        SELECT gm.user_id, u.name
        FROM group_members gm JOIN users u ON u.id = gm.user_id
        WHERE gm.group_id = %s ORDER BY u.name
    """, (group_id,)).fetchall()

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        total_amount = request.form.get('total_amount', 0, type=float)
        paid_by = request.form.get('paid_by', type=int)
        split_type = request.form.get('split_type', 'equal')
        note = request.form.get('note', '').strip()
        participant_ids = request.form.getlist('participants', type=int)

        # Validation
        if not title or total_amount <= 0 or not paid_by or not participant_ids:
            flash('Please fill in all required fields and select participants.', 'danger')
            db.close()
            return render_template('groups/add_expense.html', group=group, members=members)

        # Create expense
        cur = db.execute(
            "INSERT INTO expenses (group_id, title, total_amount, paid_by, split_type, note) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (group_id, title, total_amount, paid_by, split_type, note)
        )
        expense_id = cur.fetchone()['id']

        # Calculate splits
        if split_type == 'equal':
            per_person = round(total_amount / len(participant_ids), 2)
            # Adjust last person for rounding errors
            for idx, uid in enumerate(participant_ids):
                amt = per_person if idx < len(participant_ids) - 1 else round(total_amount - per_person * (len(participant_ids) - 1), 2)
                db.execute(
                    "INSERT INTO expense_participants (expense_id, user_id, amount_owed) VALUES (%s, %s, %s)",
                    (expense_id, uid, amt)
                )
        else:
            # Custom split – amounts passed as custom_amount_<user_id>
            total_custom = 0
            for uid in participant_ids:
                amt = request.form.get(f'custom_amount_{uid}', 0, type=float)
                total_custom += amt
                db.execute(
                    "INSERT INTO expense_participants (expense_id, user_id, amount_owed) VALUES (%s, %s, %s)",
                    (expense_id, uid, round(amt, 2))
                )
            if abs(total_custom - total_amount) > 0.05:
                db.rollback()
                db.close()
                flash(f'Custom amounts (₹{total_custom:.2f}) must sum to total (₹{total_amount:.2f}).', 'danger')
                return render_template('groups/add_expense.html', group=group, members=members)

        # Activity feed system message
        paid_by_name = next((m['name'] for m in members if m['user_id'] == paid_by), 'Someone')
        participants_names = ', '.join(m['name'] for m in members if m['user_id'] in participant_ids)
        _post_system_message(db, group_id,
            f"💰 {paid_by_name} added expense '{title}' of ₹{total_amount:.2f} split among {participants_names}.")

        # ── Notify ALL group members (except payer) about the new expense ──
        expense_link = url_for('group.dashboard', group_id=group_id)
        send_group_notification(
            db, group_id,
            title=f"💰 New Expense in '{group['name']}'",
            message=f"{paid_by_name} added '{title}' — ₹{total_amount:.2f} split among {participants_names}.",
            notif_type='expense',
            link=expense_link,
            exclude_user_id=paid_by
        )

        db.commit()
        db.close()
        log_event('💰', 'EXPENSE ADDED', f"Group:{group_id}  {title}  ₹{total_amount}", BGREEN)
        flash(f"Expense '{title}' added! All members have been notified.", 'success')
        return redirect(url_for('group.dashboard', group_id=group_id))

    db.close()
    return render_template('groups/add_expense.html', group=group, members=members)


# ══════════════════════════════════════════════════════════════════════════════
# EXPENSE DETAIL
# ══════════════════════════════════════════════════════════════════════════════
@group_bp.route('/<int:group_id>/expense/<int:expense_id>')
@login_required
def expense_detail(group_id, expense_id):
    db = get_db()
    user_id = session['user_id']

    group = db.execute("SELECT * FROM groups WHERE id = %s", (group_id,)).fetchone()
    membership = _require_membership(db, group_id, user_id)
    if not group or not membership:
        db.close()
        return redirect(url_for('group.list_groups'))

    expense = db.execute("""
        SELECT e.*, u.name AS paid_by_name
        FROM expenses e JOIN users u ON u.id = e.paid_by
        WHERE e.id = %s AND e.group_id = %s
    """, (expense_id, group_id)).fetchone()

    if not expense:
        flash('Expense not found.', 'danger')
        db.close()
        return redirect(url_for('group.dashboard', group_id=group_id))

    participants = db.execute("""
        SELECT ep.*, u.name AS user_name
        FROM expense_participants ep JOIN users u ON u.id = ep.user_id
        WHERE ep.expense_id = %s ORDER BY u.name
    """, (expense_id,)).fetchall()

    db.close()
    return render_template('groups/expense_detail.html', group=group, expense=expense,
                           participants=participants, membership=membership)


# ══════════════════════════════════════════════════════════════════════════════
# SETTLE UP  (Done button OR proof screenshot upload)
# ══════════════════════════════════════════════════════════════════════════════
@group_bp.route('/<int:group_id>/settle', methods=['POST'])
@login_required
def settle(group_id):
    db = get_db()
    user_id = session['user_id']

    membership = _require_membership(db, group_id, user_id)
    if not membership:
        db.close()
        return redirect(url_for('group.list_groups'))

    to_user_id = request.form.get('to_user_id', type=int)
    amount     = request.form.get('amount', 0, type=float)
    note       = request.form.get('settle_note', '').strip()

    if not to_user_id or amount <= 0:
        flash('Invalid settlement details.', 'danger')
        db.close()
        return redirect(url_for('group.dashboard', group_id=group_id))

    to_user = db.execute("SELECT name FROM users WHERE id = %s", (to_user_id,)).fetchone()
    if not to_user:
        flash('User not found.', 'danger')
        db.close()
        return redirect(url_for('group.dashboard', group_id=group_id))

    # ── Optional proof screenshot upload ─────────────────────────────
    proof_filename = None
    proof_file = request.files.get('proof_image')
    if proof_file and proof_file.filename and _allowed_proof(proof_file.filename):
        ext = proof_file.filename.rsplit('.', 1)[1].lower()
        import time as _t
        safe_name = secure_filename(f"settle_{user_id}_{to_user_id}_{int(_t.time())}.{ext}")
        upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'proofs')
        os.makedirs(upload_dir, exist_ok=True)
        proof_file.save(os.path.join(upload_dir, safe_name))
        proof_filename = f"proofs/{safe_name}"

    # pending_confirmation when proof attached → recipient must confirm
    # settled immediately if just "Done" button (no proof)
    status = 'pending_confirmation' if proof_filename else 'settled'

    cur = db.execute(
        """INSERT INTO settlements
               (group_id, from_user, to_user, amount, status, note, proof_image, settled_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, NOW()) RETURNING id""",
        (group_id, user_id, to_user_id, round(amount, 2), status, note or None, proof_filename)
    )
    settlement_id = cur.fetchone()['id']

    action_str = "submitted payment proof for" if proof_filename else "settled"
    _post_system_message(db, group_id,
        f"✅ {session['user_name']} {action_str} ₹{amount:.2f} to {to_user['name']}.")

    # ── Notify recipient ─────────────────────────────────────────────
    group_row  = db.execute("SELECT name FROM groups WHERE id = %s", (group_id,)).fetchone()
    settle_link = url_for('group.settlement_detail', group_id=group_id, settlement_id=settlement_id)

    if proof_filename:
        notif_title = "📸 Payment Proof Received"
        notif_msg   = (f"{session['user_name']} sent payment proof of ₹{amount:.2f} "
                       f"in '{group_row['name']}'. Tap to view & confirm.")
    else:
        notif_title = "✅ Payment Marked Settled"
        notif_msg   = (f"{session['user_name']} marked ₹{amount:.2f} as settled "
                       f"in '{group_row['name']}'. Please confirm if you received it.")

    db.execute(
        "INSERT INTO notifications (user_id, title, message, type, link) VALUES (%s, %s, %s, %s, %s)",
        (to_user_id, notif_title, notif_msg, 'payment', settle_link)
    )

    db.commit()
    db.close()
    log_event('✅', 'SETTLEMENT', f"{session['user_name']} → {to_user['name']}  ₹{amount}", BYELLOW)

    if proof_filename:
        flash(f"Payment proof submitted to {to_user['name']}! They will confirm receipt.", 'success')
    else:
        flash(f"₹{amount:.2f} marked as settled. {to_user['name']} has been notified to confirm.", 'success')
    return redirect(url_for('group.dashboard', group_id=group_id))


# ══════════════════════════════════════════════════════════════════════════════
# SETTLEMENT DETAIL  (view proof + confirm button)
# ══════════════════════════════════════════════════════════════════════════════
@group_bp.route('/<int:group_id>/settlement/<int:settlement_id>')
@login_required
def settlement_detail(group_id, settlement_id):
    db  = get_db()
    user_id = session['user_id']

    group      = db.execute("SELECT * FROM groups WHERE id = %s", (group_id,)).fetchone()
    membership = _require_membership(db, group_id, user_id)
    if not group or not membership:
        db.close()
        return redirect(url_for('group.list_groups'))

    s = db.execute("""
        SELECT s.*,
               uf.name  AS from_name,
               ut.name  AS to_name,
               uc.name  AS confirmed_by_name
        FROM settlements s
        JOIN users uf ON uf.id = s.from_user
        JOIN users ut ON ut.id = s.to_user
        LEFT JOIN users uc ON uc.id = s.confirmed_by
        WHERE s.id = %s AND s.group_id = %s
    """, (settlement_id, group_id)).fetchone()

    if not s:
        flash('Settlement not found.', 'danger')
        db.close()
        return redirect(url_for('group.dashboard', group_id=group_id))

    db.close()
    return render_template('groups/settlement_detail.html',
                           group=group, s=s, membership=membership)


# ══════════════════════════════════════════════════════════════════════════════
# CONFIRM SETTLEMENT  (recipient taps “Confirm Received”)
# ══════════════════════════════════════════════════════════════════════════════
@group_bp.route('/<int:group_id>/settlement/<int:settlement_id>/confirm', methods=['POST'])
@login_required
def confirm_settlement(group_id, settlement_id):
    db      = get_db()
    user_id = session['user_id']

    membership = _require_membership(db, group_id, user_id)
    if not membership:
        db.close()
        return redirect(url_for('group.list_groups'))

    s = db.execute(
        "SELECT * FROM settlements WHERE id = %s AND group_id = %s",
        (settlement_id, group_id)
    ).fetchone()

    if not s:
        flash('Settlement not found.', 'danger')
        db.close()
        return redirect(url_for('group.dashboard', group_id=group_id))

    if s['to_user'] != user_id:
        flash('Only the payment recipient can confirm this settlement.', 'danger')
        db.close()
        return redirect(url_for('group.settlement_detail',
                                group_id=group_id, settlement_id=settlement_id))

    if s['confirmed_at']:
        flash('This settlement was already confirmed.', 'info')
        db.close()
        return redirect(url_for('group.settlement_detail',
                                group_id=group_id, settlement_id=settlement_id))

    db.execute(
        "UPDATE settlements SET status='settled', confirmed_at=NOW(), confirmed_by=%s WHERE id=%s",
        (user_id, settlement_id)
    )

    # Notify the payer
    group_row = db.execute("SELECT name FROM groups WHERE id = %s", (group_id,)).fetchone()
    settle_link = url_for('group.settlement_detail', group_id=group_id, settlement_id=settlement_id)
    db.execute(
        "INSERT INTO notifications (user_id, title, message, type, link) VALUES (%s, %s, %s, %s, %s)",
        (s['from_user'],
         "✅ Payment Confirmed!",
         f"{session['user_name']} confirmed your payment of ₹{s['amount']:.2f} in '{group_row['name']}'.",
         'payment',
         settle_link)
    )

    from_user = db.execute("SELECT name FROM users WHERE id=%s", (s['from_user'],)).fetchone()
    _post_system_message(db, group_id,
        f"✅ {session['user_name']} confirmed receipt of ₹{s['amount']:.2f} from {from_user['name']}.")

    db.commit()
    db.close()
    log_event('✅', 'CONFIRMED', f"{session['user_name']} confirmed ₹{s['amount']}", BGREEN)
    flash('Payment confirmed! The payer has been notified.', 'success')
    return redirect(url_for('group.dashboard', group_id=group_id))




# ══════════════════════════════════════════════════════════════════════════════
# ACTIVITY FEED
# ══════════════════════════════════════════════════════════════════════════════
@group_bp.route('/<int:group_id>/feed')
@login_required
def activity_feed(group_id):
    db = get_db()
    user_id = session['user_id']

    group = db.execute("SELECT * FROM groups WHERE id = %s", (group_id,)).fetchone()
    membership = _require_membership(db, group_id, user_id)
    if not group or not membership:
        db.close()
        return redirect(url_for('group.list_groups'))

    messages = db.execute("""
        SELECT m.*, u.name AS sender_name
        FROM messages m
        LEFT JOIN users u ON u.id = m.sender_id
        WHERE m.group_id = %s
        ORDER BY m.created_at ASC
    """, (group_id,)).fetchall()

    # Pending balances for quick settle button
    owed_rows = db.execute("""
        SELECT u.name AS creditor_name, u.id AS creditor_id,
               COALESCE(SUM(ep.amount_owed), 0) AS total_owed
        FROM expense_participants ep
        JOIN expenses e ON e.id = ep.expense_id
        JOIN users u ON u.id = e.paid_by
        WHERE ep.user_id = %s AND e.group_id = %s AND e.paid_by != %s
        GROUP BY u.id, u.name
    """, (user_id, group_id, user_id)).fetchall()

    settled_paid = db.execute("""
        SELECT to_user, COALESCE(SUM(amount), 0) AS settled
        FROM settlements
        WHERE from_user = %s AND group_id = %s AND status = 'settled'
        GROUP BY to_user
    """, (user_id, group_id)).fetchall()
    settled_paid_map = {r['to_user']: r['settled'] for r in settled_paid}

    balances = []
    for r in owed_rows:
        net = max(0, r['total_owed'] - settled_paid_map.get(r['creditor_id'], 0))
        if net > 0.005:
            balances.append({'person': r['creditor_name'], 'person_id': r['creditor_id'],
                             'amount': round(net, 2)})

    db.close()
    return render_template('groups/activity_feed.html', group=group, membership=membership,
                           messages=messages, balances=balances)


# ══════════════════════════════════════════════════════════════════════════════
# POST MESSAGE (AJAX)
# ══════════════════════════════════════════════════════════════════════════════
@group_bp.route('/<int:group_id>/message', methods=['POST'])
@login_required
def post_message(group_id):
    db      = get_db()
    user_id = session['user_id']

    membership = _require_membership(db, group_id, user_id)
    if not membership:
        db.close()
        return jsonify({'success': False, 'error': 'Not a member'}), 403

    data = request.get_json(silent=True) or {}
    text = (data.get('message') or request.form.get('message', '')).strip()
    iv   = data.get('iv')           # base64 IV when encrypted
    is_enc = bool(iv and text)      # True only when both ciphertext + IV present

    if not text:
        db.close()
        return jsonify({'success': False, 'error': 'Empty message'}), 400

    db.execute(
        "INSERT INTO messages (group_id, sender_id, message, type, iv, is_encrypted)"
        " VALUES (%s, %s, %s, 'user', %s, %s)",
        (group_id, user_id, text, iv, is_enc)
    )
    db.commit()
    db.close()
    return jsonify({'success': True, 'sender': session['user_name'], 'message': text})


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN: ALL GROUPS VIEW
# ══════════════════════════════════════════════════════════════════════════════
@group_bp.route('/admin/all')
@admin_required
def admin_all_groups():
    db = get_db()
    groups = db.execute("""
        SELECT g.*, u.name AS creator_name,
               COUNT(DISTINCT gm.id) AS member_count,
               COUNT(DISTINCT e.id) AS expense_count
        FROM groups g
        JOIN users u ON u.id = g.created_by
        LEFT JOIN group_members gm ON gm.group_id = g.id
        LEFT JOIN expenses e ON e.group_id = g.id
        GROUP BY g.id, u.name
        ORDER BY g.created_at DESC
    """).fetchall()
    db.close()
    return render_template('groups/admin_groups.html', groups=groups)


# ══════════════════════════════════════════════════════════════════════════════
# DELETE GROUP (admin only)
# ══════════════════════════════════════════════════════════════════════════════
@group_bp.route('/<int:group_id>/delete', methods=['POST'])
@login_required
def delete_group(group_id):
    db = get_db()
    user_id = session['user_id']
    group = db.execute("SELECT * FROM groups WHERE id = %s", (group_id,)).fetchone()

    if not group:
        db.close()
        flash('Group not found.', 'danger')
        return redirect(url_for('group.list_groups'))

    # Only creator or site admin can delete
    if group['created_by'] != user_id and session.get('role') != 'admin':
        db.close()
        flash('Only the group creator can delete the group.', 'danger')
        return redirect(url_for('group.dashboard', group_id=group_id))

    db.execute("DELETE FROM groups WHERE id = %s", (group_id,))
    db.commit()
    db.close()
    flash('Group deleted.', 'success')
    return redirect(url_for('group.list_groups'))


# ══════════════════════════════════════════════════════════════════════════════
# POLL NEW MESSAGES  GET /groups/<id>/messages/poll?after=<last_msg_id>
# ══════════════════════════════════════════════════════════════════════════════
@group_bp.route('/<int:group_id>/messages/poll')
@login_required
def poll_messages(group_id):
    db      = get_db()
    user_id = session['user_id']

    if not _require_membership(db, group_id, user_id):
        db.close()
        return jsonify({'success': False}), 403

    after_id = int(request.args.get('after', 0))

    rows = db.execute("""
        SELECT m.id, m.group_id, m.sender_id, m.message, m.type,
               m.created_at::text AS created_at,
               m.iv, m.is_encrypted,
               u.name AS sender_name
        FROM messages m
        LEFT JOIN users u ON u.id = m.sender_id
        WHERE m.group_id = %s AND m.id > %s
        ORDER BY m.created_at ASC
    """, (group_id, after_id)).fetchall()

    db.close()
    return jsonify({
        'success': True,
        'messages': [dict(r) for r in rows],
        'viewer_id': user_id
    })


# ══════════════════════════════════════════════════════════════════════════════
# DELETE SINGLE MESSAGE  DELETE /groups/<id>/messages/<msg_id>
# ══════════════════════════════════════════════════════════════════════════════
@group_bp.route('/<int:group_id>/messages/<int:msg_id>/delete', methods=['POST'])
@login_required
def delete_message(group_id, msg_id):
    db      = get_db()
    user_id = session['user_id']

    msg = db.execute("SELECT * FROM messages WHERE id = %s AND group_id = %s",
                     (msg_id, group_id)).fetchone()
    if not msg:
        db.close()
        return jsonify({'success': False, 'error': 'Not found'}), 404

    # Allow if: own message  OR  site admin  OR  group admin
    membership = _get_membership(db, group_id, user_id)
    is_group_admin = membership and membership['role'] == 'admin'
    is_site_admin  = session.get('role') == 'admin'
    is_own         = msg['sender_id'] == user_id

    if not (is_own or is_group_admin or is_site_admin):
        db.close()
        return jsonify({'success': False, 'error': 'Not allowed'}), 403

    db.execute("DELETE FROM messages WHERE id = %s", (msg_id,))
    db.commit()
    db.close()
    return jsonify({'success': True, 'deleted_id': msg_id})


# ══════════════════════════════════════════════════════════════════════════════
# CLEAR ALL CHAT  POST /groups/<id>/messages/clear
# ══════════════════════════════════════════════════════════════════════════════
@group_bp.route('/<int:group_id>/messages/clear', methods=['POST'])
@login_required
def clear_chat(group_id):
    db      = get_db()
    user_id = session['user_id']

    group = db.execute("SELECT * FROM groups WHERE id = %s", (group_id,)).fetchone()
    if not group:
        db.close()
        return jsonify({'success': False, 'error': 'Group not found'}), 404

    membership = _get_membership(db, group_id, user_id)
    is_group_admin = membership and membership['role'] == 'admin'
    is_site_admin  = session.get('role') == 'admin'
    is_creator     = group['created_by'] == user_id

    if not (is_creator or is_group_admin or is_site_admin):
        db.close()
        return jsonify({'success': False, 'error': 'Only group admins can clear chat'}), 403

    deleted = db.execute(
        "DELETE FROM messages WHERE group_id = %s RETURNING id", (group_id,)
    ).fetchall()
    db.commit()
    db.close()
    return jsonify({'success': True, 'cleared': len(deleted)})


# ══════════════════════════════════════════════════════════════════════════════
# E2EE: REGISTER USER PUBLIC KEY  POST /groups/keys/register
# ══════════════════════════════════════════════════════════════════════════════
@group_bp.route('/keys/register', methods=['POST'])
@login_required
def register_public_key():
    data = request.get_json(silent=True) or {}
    pub  = data.get('public_key', '').strip()
    if not pub:
        return jsonify({'success': False, 'error': 'No key'}), 400
    db = get_db()
    db.execute("UPDATE users SET public_key = %s WHERE id = %s",
               (pub, session['user_id']))
    db.commit()
    db.close()
    return jsonify({'success': True})


# ══════════════════════════════════════════════════════════════════════════════
# E2EE: GET GROUP KEY INFO  GET /groups/<id>/keys
# ══════════════════════════════════════════════════════════════════════════════
@group_bp.route('/<int:group_id>/keys')
@login_required
def get_group_keys(group_id):
    db      = get_db()
    user_id = session['user_id']

    if not _require_membership(db, group_id, user_id):
        db.close()
        return jsonify({'success': False}), 403

    members = db.execute("""
        SELECT u.id, u.name, u.public_key,
               gm.encrypted_group_key IS NOT NULL AS has_key
        FROM group_members gm
        JOIN users u ON u.id = gm.user_id
        WHERE gm.group_id = %s
    """, (group_id,)).fetchall()

    my_row = db.execute("""
        SELECT encrypted_group_key FROM group_members
        WHERE group_id = %s AND user_id = %s
    """, (group_id, user_id)).fetchone()

    db.close()
    return jsonify({
        'success': True,
        'my_encrypted_key': my_row['encrypted_group_key'] if my_row else None,
        'members': [{'id': m['id'], 'name': m['name'],
                     'public_key': m['public_key'], 'has_key': bool(m['has_key'])}
                    for m in members]
    })


# ══════════════════════════════════════════════════════════════════════════════
# E2EE: DISTRIBUTE GROUP KEY  POST /groups/<id>/keys/distribute
# ══════════════════════════════════════════════════════════════════════════════
@group_bp.route('/<int:group_id>/keys/distribute', methods=['POST'])
@login_required
def distribute_group_keys(group_id):
    db      = get_db()
    user_id = session['user_id']

    if not _require_membership(db, group_id, user_id):
        db.close()
        return jsonify({'success': False}), 403

    data = request.get_json(silent=True) or {}
    # [{ "user_id": N, "encrypted_key": "base64..." }, ...]
    for item in data.get('keys', []):
        db.execute("""
            UPDATE group_members SET encrypted_group_key = %s
            WHERE group_id = %s AND user_id = %s
        """, (item['encrypted_key'], group_id, item['user_id']))
    db.commit()
    db.close()
    return jsonify({'success': True})
