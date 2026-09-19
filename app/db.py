"""
db.py
SQLite persistence layer for GitHub Push Manager.

Schema:
    projects(id, name, created_at)
    repositories(id, project_id, repo_name, repo_url, html_url, clone_url,
                 folder_path, commit_message, status, branch,
                 created_at, last_push_at)

Design notes:
- We never store the GitHub token here. Tokens live in the OS keyring
  (see github_client.py). This table only stores non-secret config.
- `status` is a free-text field driven by the UI/worker layer, but the
  application only ever writes one of the canonical values:
      "Not-UP" | "Pushing" | "Success" | "Failed"
  Older databases created by earlier versions of this app may contain
  legacy values ("Ready", "Existing", "No Folder") -- `init_db()`
  migrates those in place the first time the new version runs, so
  existing app.db files (and the projects/repos saved in them) are
  never dropped or reset.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

DB_PATH = Path.home() / ".github_push_manager" / "app.db"

# Canonical status values used everywhere in the app.
STATUS_NOT_UP = "Not-UP"
STATUS_PUSHING = "Pushing"
STATUS_SUCCESS = "Success"
STATUS_FAILED = "Failed"

# Legacy status values from older versions of the app, mapped to the
# closest canonical value during migration.
_LEGACY_STATUS_MAP = {
    "Ready": STATUS_NOT_UP,
    "Existing": STATUS_NOT_UP,
    "No Folder": STATUS_NOT_UP,
}


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring an existing database up to the current schema without ever
    dropping data. Safe to call every startup (all operations are
    idempotent / guarded by column-existence checks)."""
    cols = _column_names(conn, "repositories")

    # Added in this version: real GitHub URLs kept separately so the UI
    # can open the web page (html_url) while still using the correct
    # clone URL for `git remote` (clone_url), independent of what the
    # legacy single `repo_url` column happened to hold.
    if "html_url" not in cols:
        conn.execute("ALTER TABLE repositories ADD COLUMN html_url TEXT")
    if "clone_url" not in cols:
        conn.execute("ALTER TABLE repositories ADD COLUMN clone_url TEXT")

    cols = _column_names(conn, "repositories")
    if "clone_url" in cols:
        # Backfill clone_url from the legacy repo_url column so existing
        # repositories keep working with push/git operations unchanged.
        conn.execute(
            "UPDATE repositories SET clone_url = repo_url "
            "WHERE (clone_url IS NULL OR clone_url = '') "
            "AND repo_url IS NOT NULL AND repo_url != ''"
        )

    # Consolidate legacy status labels into the canonical set used by
    # the current UI (Not-UP / Pushing / Success / Failed). Any repo
    # that was mid-push when the app last closed is not actually
    # pushing anymore, so "Pushing" also gets reset to "Not-UP".
    for legacy, canonical in _LEGACY_STATUS_MAP.items():
        conn.execute(
            "UPDATE repositories SET status = ? WHERE status = ?",
            (canonical, legacy),
        )
    conn.execute(
        "UPDATE repositories SET status = ? WHERE status = ?",
        (STATUS_NOT_UP, STATUS_PUSHING),
    )


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL UNIQUE,
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS repositories (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                repo_name       TEXT NOT NULL,
                repo_url        TEXT,
                folder_path     TEXT,
                commit_message  TEXT,
                status          TEXT NOT NULL DEFAULT 'Not-UP',
                branch          TEXT NOT NULL DEFAULT 'main',
                created_at      TEXT NOT NULL,
                last_push_at    TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_repo_project ON repositories(project_id);
            """
        )
        _migrate(conn)


@dataclass
class Repository:
    id: Optional[int]
    project_id: int
    repo_name: str
    repo_url: str = ""       # kept for backward compatibility; mirrors clone_url
    html_url: str = ""       # web page, e.g. https://github.com/user/Bai-1
    clone_url: str = ""      # used for `git remote add/set-url origin`
    folder_path: str = ""
    commit_message: str = ""
    status: str = STATUS_NOT_UP
    branch: str = "main"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    last_push_at: Optional[str] = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Repository":
        keys = row.keys()
        clone_url = row["clone_url"] if "clone_url" in keys else None
        html_url = row["html_url"] if "html_url" in keys else None
        repo_url = row["repo_url"] or ""
        return cls(
            id=row["id"],
            project_id=row["project_id"],
            repo_name=row["repo_name"],
            repo_url=repo_url,
            html_url=html_url or "",
            clone_url=clone_url or repo_url or "",
            folder_path=row["folder_path"] or "",
            commit_message=row["commit_message"] or "",
            status=row["status"],
            branch=row["branch"],
            created_at=row["created_at"],
            last_push_at=row["last_push_at"],
        )


@dataclass
class Project:
    id: Optional[int]
    name: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Project":
        return cls(id=row["id"], name=row["name"], created_at=row["created_at"])


# ---------------------------------------------------------------- Projects

def create_project(name: str) -> Project:
    p = Project(id=None, name=name)
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO projects (name, created_at) VALUES (?, ?)",
            (p.name, p.created_at),
        )
        p.id = cur.lastrowid
    return p


def list_projects() -> list[Project]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    return [Project.from_row(r) for r in rows]


def get_project(project_id: int) -> Optional[Project]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return Project.from_row(row) if row else None


def delete_project(project_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))


# ------------------------------------------------------------ Repositories

def add_repository(repo: Repository) -> Repository:
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO repositories
               (project_id, repo_name, repo_url, html_url, clone_url,
                folder_path, commit_message, status, branch, created_at,
                last_push_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                repo.project_id, repo.repo_name,
                repo.clone_url or repo.repo_url, repo.html_url, repo.clone_url,
                repo.folder_path, repo.commit_message, repo.status,
                repo.branch, repo.created_at, repo.last_push_at,
            ),
        )
        repo.id = cur.lastrowid
    return repo


def list_repositories(project_id: int) -> list[Repository]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM repositories WHERE project_id = ? ORDER BY id ASC",
            (project_id,),
        ).fetchall()
    return [Repository.from_row(r) for r in rows]


def repository_name_exists(project_id: int, repo_name: str) -> bool:
    """Case-insensitive check used to avoid creating duplicate DB
    records for a repository name already tracked in this project."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM repositories WHERE project_id = ? AND lower(repo_name) = lower(?) LIMIT 1",
            (project_id, repo_name),
        ).fetchone()
    return row is not None


def update_repository(repo: Repository) -> None:
    with _connect() as conn:
        conn.execute(
            """UPDATE repositories SET
                 repo_name=?, repo_url=?, html_url=?, clone_url=?, folder_path=?,
                 commit_message=?, status=?, branch=?, last_push_at=?
               WHERE id=?""",
            (
                repo.repo_name, repo.clone_url or repo.repo_url, repo.html_url,
                repo.clone_url, repo.folder_path, repo.commit_message,
                repo.status, repo.branch, repo.last_push_at, repo.id,
            ),
        )


def delete_repository(repo_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM repositories WHERE id = ?", (repo_id,))
