import os

class Config:
    # Secret key — always override via environment variable in production
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

    # PostgreSQL connection URL
    # In production (Render), set DATABASE_URL environment variable
    DATABASE_URL = os.environ.get(
        'DATABASE_URL',
        'postgresql://canteen_kdlc_user:p2k0jY5LgDShMXUPCUftqjW6m0FaUMfo@dpg-d7k23o9o3t8c738pu4dg-a.oregon-postgres.render.com/canteen_kdlc'
    )

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024  # 2 MB max upload

    # Production flags
    FLASK_ENV = os.environ.get('FLASK_ENV', 'development')
    DEBUG = FLASK_ENV != 'production'
