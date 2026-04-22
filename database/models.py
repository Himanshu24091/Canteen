import psycopg2
import psycopg2.extras
import os
from config import Config


class _Cursor:
    """Thin wrapper around psycopg2 cursor to mimic sqlite3 Row-dict interface."""
    def __init__(self, cur):
        self._cur = cur

    def execute(self, sql, params=()):
        # Replace SQLite ? placeholders with PostgreSQL %s
        pg_sql = sql.replace('?', '%s')
        # Convert SQLite date/time functions to PostgreSQL equivalents
        pg_sql = _convert_sql(pg_sql)
        self._cur.execute(pg_sql, params)
        return self

    def executemany(self, sql, seq):
        pg_sql = sql.replace('?', '%s')
        pg_sql = _convert_sql(pg_sql)
        self._cur.executemany(pg_sql, seq)
        return self

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    @property
    def lastrowid(self):
        return self._cur.fetchone()[0]

    def close(self):
        self._cur.close()


class _Connection:
    """Thin wrapper around psycopg2 connection to mimic sqlite3 interface."""
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        wrapper = _Cursor(cur)
        return wrapper.execute(sql, params)

    def executemany(self, sql, seq):
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        wrapper = _Cursor(cur)
        return wrapper.executemany(sql, seq)

    def executescript(self, script):
        """Execute a multi-statement SQL script (used by init_db)."""
        cur = self._conn.cursor()
        statements = [s.strip() for s in script.split(';') if s.strip()]
        for stmt in statements:
            cur.execute(stmt)
        cur.close()

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def _convert_sql(sql):
    """Convert SQLite-specific SQL syntax to PostgreSQL."""
    import re

    # date('now','localtime')  →  CURRENT_DATE
    sql = re.sub(r"date\('now'\s*,\s*'localtime'\)", 'CURRENT_DATE', sql, flags=re.IGNORECASE)
    # date(column)  →  column::date
    sql = re.sub(r"date\(([^)]+)\)", r'\1::date', sql, flags=re.IGNORECASE)

    # datetime('now','localtime','-N days')  →  NOW() - INTERVAL 'N days'
    def replace_datetime_offset(m):
        n = m.group(1)
        return f"(NOW() - INTERVAL '{n} days')"
    sql = re.sub(
        r"datetime\('now'\s*,\s*'localtime'\s*,\s*'-(\d+)\s*days'\)",
        replace_datetime_offset, sql, flags=re.IGNORECASE
    )

    # datetime('now','localtime')  →  NOW()
    sql = re.sub(r"datetime\('now'\s*,\s*'localtime'\)", 'NOW()', sql, flags=re.IGNORECASE)

    # COALESCE(x) – already valid in PostgreSQL
    # GROUP_CONCAT(expr, sep)  →  STRING_AGG(expr, sep)
    sql = re.sub(
        r"GROUP_CONCAT\((.+?),\s*'(.+?)'\)",
        lambda m: f"STRING_AGG({m.group(1)}, '{m.group(2)}')",
        sql, flags=re.IGNORECASE | re.DOTALL
    )

    # For INSERT ... RETURNING id  (needed for lastrowid)
    # Add RETURNING id to INSERT statements that don't have it
    # We handle lastrowid specially in place_order using a modified execute
    return sql


def get_db():
    conn = psycopg2.connect(Config.DATABASE_URL)
    conn.autocommit = False
    return _Connection(conn)


def close_db(db):
    if db is not None:
        db.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    phone TEXT,
    department TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS menu_items (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    price REAL NOT NULL,
    category TEXT DEFAULT 'General',
    image_url TEXT,
    is_available INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    total_amount REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    payment_status TEXT NOT NULL DEFAULT 'unpaid',
    payment_method TEXT DEFAULT 'cash',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS order_items (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    item_name TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    price REAL NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(id),
    FOREIGN KEY (item_id) REFERENCES menu_items(id)
);

CREATE TABLE IF NOT EXISTS payments (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    order_id INTEGER,
    amount REAL NOT NULL,
    method TEXT DEFAULT 'cash',
    status TEXT NOT NULL DEFAULT 'pending',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (order_id) REFERENCES orders(id)
);

CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY,
    user_id INTEGER,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    type TEXT DEFAULT 'info',
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
"""
