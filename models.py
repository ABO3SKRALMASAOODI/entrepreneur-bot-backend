import sqlite3
from flask import current_app, g

def init_db(app):
    with app.app_context():
        db = get_db()
        cursor = db.cursor()

        # Create users table
        cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        is_subscribed INTEGER DEFAULT 0,
        is_verified INTEGER DEFAULT 0
            )
        ''')


        # Create email verification codes table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS email_codes (
                email TEXT PRIMARY KEY,
                code TEXT
            )
        ''')

        db.commit()
        db.close()

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(current_app.config['DATABASE'])
    db.row_factory = sqlite3.Row
    return db
