import sqlite3

def init_db():
    conn = sqlite3.connect("paas.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS deployments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_name TEXT,
            github_url TEXT,
            status TEXT,
            url TEXT,
            started_at TEXT,
            completed_at TEXT,
            deploy_time_sec REAL
        )
    """)
    conn.commit()
    conn.close()