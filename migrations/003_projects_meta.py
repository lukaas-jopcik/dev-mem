"""
003_projects_meta.py — Add is_git and last_accessed columns to projects.
"""
import sqlite3

VERSION = 3
DESCRIPTION = "Add is_git and last_accessed to projects table"


def up(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    # Add is_git column (1 = git repo, 0 = plain folder)
    try:
        cur.execute("ALTER TABLE projects ADD COLUMN is_git INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # already exists
    # Add last_accessed timestamp
    try:
        cur.execute("ALTER TABLE projects ADD COLUMN last_accessed TEXT")
    except sqlite3.OperationalError:
        pass
    # Back-fill is_git for any existing projects by checking filesystem
    import os
    rows = conn.execute("SELECT id, path FROM projects").fetchall()
    for row in rows:
        is_git = 1 if os.path.isdir(os.path.join(row[1], ".git")) else 0
        conn.execute("UPDATE projects SET is_git=? WHERE id=?", (is_git, row[0]))
    conn.commit()
