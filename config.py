import os

class Config:
    # Secret key — always override via environment variable in production
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

    # Database — use /opt/render/project/src/database on Render (persistent disk)
    # Falls back to local database/ folder in development
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DB_DIR = os.environ.get('DB_DIR', os.path.join(BASE_DIR, 'database'))
    DATABASE_PATH = os.path.join(DB_DIR, 'canteen.db')

    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024  # 2 MB max upload

    # Production flags
    FLASK_ENV = os.environ.get('FLASK_ENV', 'development')
    DEBUG = FLASK_ENV != 'production'
