import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.models import get_db, SCHEMA
from config import Config
from werkzeug.security import generate_password_hash
import sqlite3

def init_db():
    os.makedirs(os.path.dirname(Config.DATABASE_PATH), exist_ok=True)
    db = sqlite3.connect(Config.DATABASE_PATH)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    db.commit()

    # Seed admin user
    cur = db.execute("SELECT id FROM users WHERE email = 'admin@canteen.com'")
    if cur.fetchone() is None:
        db.execute(
            "INSERT INTO users (name, email, password, role) VALUES (?, ?, ?, ?)",
            ('Admin', 'admin@canteen.com', generate_password_hash('admin123'), 'admin')
        )

    # Seed demo menu items
    cur = db.execute("SELECT COUNT(*) as cnt FROM menu_items")
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
        db.executemany(
            "INSERT INTO menu_items (name, description, price, category, image_url) VALUES (?, ?, ?, ?, ?)",
            items
        )

    db.commit()
    db.close()
    print("[OK] Database initialized successfully!")
    print("   Admin credentials: admin@canteen.com / admin123")

if __name__ == '__main__':
    init_db()
