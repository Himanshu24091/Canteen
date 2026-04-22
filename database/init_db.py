import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import psycopg2
import psycopg2.extras
from config import Config
from werkzeug.security import generate_password_hash


def init_db():
    conn = psycopg2.connect(Config.DATABASE_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Create tables (run each statement separately)
    statements = [s.strip() for s in """
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
""".strip().split(';') if s.strip()]

    for stmt in statements:
        if stmt:
            cur.execute(stmt)
    conn.commit()

    # Seed admin user
    cur.execute("SELECT id FROM users WHERE email = %s", ('admin@canteen.com',))
    if cur.fetchone() is None:
        cur.execute(
            "INSERT INTO users (name, email, password, role) VALUES (%s, %s, %s, %s)",
            ('Admin', 'admin@canteen.com', generate_password_hash('admin123'), 'admin')
        )

    # Seed demo menu items
    cur.execute("SELECT COUNT(*) as cnt FROM menu_items")
    row = cur.fetchone()
    if row['cnt'] == 0:
        items = [
            ('Veg Thali', 'Full meal with rice, dal, sabzi, roti', 60.0, 'Meals', None),
            ('Non-Veg Thali', 'Full meal with chicken/fish, rice, roti', 90.0, 'Meals', None),
            ('Paneer Sandwich', 'Grilled paneer with veggies', 35.0, 'Snacks', None),
            ('Masala Chai', 'Hot spiced tea', 10.0, 'Beverages', None),
            ('Cold Coffee', 'Chilled blended coffee', 30.0, 'Beverages', None),
            ('Samosa', 'Crispy fried samosa with chutney', 15.0, 'Snacks', None),
            ('Idli Sambhar', '3 idlis with sambhar and coconut chutney', 40.0, 'Breakfast', None),
            ('Poha', 'Flattened rice with onion and spices', 25.0, 'Breakfast', None),
            ('Pasta', 'Creamy white sauce pasta', 55.0, 'Snacks', None),
            ('Fresh Lime Soda', 'Sweet or salted lemon soda', 20.0, 'Beverages', None),
        ]
        cur.executemany(
            "INSERT INTO menu_items (name, description, price, category, image_url) VALUES (%s, %s, %s, %s, %s)",
            items
        )

    conn.commit()
    cur.close()
    conn.close()
    print("[OK] PostgreSQL database initialized successfully!")
    print("   Admin credentials: admin@canteen.com / admin123")


if __name__ == '__main__':
    init_db()
