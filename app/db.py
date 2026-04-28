# db.py
import sqlite3
from datetime import datetime

DB_PATH = "/k8s/paas/deployments.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS deployments (
            app_name    TEXT PRIMARY KEY,
            image       TEXT,
            port        INTEGER,
            url         TEXT,
            status      TEXT,
            started_at  TEXT,
            finished_at TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_deployment(app_name, image, port, url, status, started_at, finished_at=None):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT OR REPLACE INTO deployments
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (app_name, image, port, url, status, started_at, finished_at))
    conn.commit()
    conn.close()

def get_all_deployments():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT * FROM deployments").fetchall()
    conn.close()
    return rows

def get_deployment(app_name):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT * FROM deployments WHERE app_name = ?", (app_name,)
    ).fetchone()
    conn.close()
    return row
