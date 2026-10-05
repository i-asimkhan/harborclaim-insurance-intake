"""
Persistent storage for HarborClaim -- SQLite-backed claims database,
on-disk evidence (document) storage, and the two-role account model
(claimants and adjusters).

Replaces the in-memory `app.CLAIMS` dict described in the Design Deliverable
as step 7 (Claims Database) and step 1 (document/evidence storage). Uses only
the standard library (`sqlite3`, `pathlib`, `json`) -- no new dependency.

Accounts are deliberately asymmetric, on purpose, mirroring how a real
insurer actually provisions these two kinds of users:
  - Claimants are self-service: `get_or_create_user` creates the account on
    first Google login, no approval step. Anyone with a Google account can
    file a claim.
  - Adjusters are provisioned, not self-service: `create_adjuster` generates
    a username and a random password (there's no sign-up form, and no
    "become an adjuster" button anywhere in the app), matching the real-world
    fact that adjusters need a state license before they can hold the role,
    not just an email address. Passwords are salted and hashed with
    `hashlib.scrypt` (standard library, no new dependency) -- never stored or
    logged in plaintext after `create_adjuster` returns it once.

A fresh `sqlite3.connect()` is opened per call rather than held open, since
FastAPI's sync routes run in a thread pool and SQLite connections aren't
safe to share across threads without extra care. SQLite handles many short
connections against one file fine at this scale.
"""

import hashlib
import hmac
import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DB_PATH = DATA_DIR / "harborclaim.db"
UPLOADS_DIR = DATA_DIR / "uploads"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    name TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS adjusters (
    username TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    name TEXT,
    linked_claimant_email TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claims (
    claim_id TEXT PRIMARY KEY,
    claimant_email TEXT NOT NULL,
    policy_id TEXT NOT NULL,
    incident_date TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL,
    missing TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL REFERENCES claims(claim_id),
    filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    content_type TEXT,
    size_bytes INTEGER NOT NULL,
    uploaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL REFERENCES claims(claim_id),
    status TEXT NOT NULL,
    at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS adjuster_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL REFERENCES claims(claim_id),
    decision TEXT NOT NULL,
    adjuster_username TEXT NOT NULL,
    decided_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS login_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    identifier TEXT NOT NULL,
    event TEXT NOT NULL,
    at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claim_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL REFERENCES claims(claim_id),
    field TEXT NOT NULL,
    value TEXT NOT NULL,
    source TEXT NOT NULL,
    extracted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claim_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL REFERENCES claims(claim_id),
    summary_text TEXT NOT NULL,
    generated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL REFERENCES claims(claim_id),
    claimant_email TEXT NOT NULL,
    channel TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    read_at TEXT
);
"""

# A fresh checkout (or a DB created before accounts existed) may already have
# a `claims` table without `claimant_email`. SQLite can't add a NOT NULL
# column with no default to an existing table in one step, so this adds it
# as nullable if missing -- old rows just show no owner, which is fine for a
# dev database that's gitignored and never held real data.
_MIGRATIONS = [
    "ALTER TABLE claims ADD COLUMN claimant_email TEXT",
]

# The `adjusters` and `adjuster_decisions` tables changed shape (Google-email
# allowlist -> username/password accounts). A dev DB created before that
# change has the old columns; since this is gitignored data that was never
# real, the simplest fix is to drop and let CREATE TABLE IF NOT EXISTS above
# rebuild it, rather than writing a real migration for a table that never
# held anything worth keeping.
_STALE_SCHEMA_TABLES = {
    "adjusters": {
        "username", "password_hash", "salt", "name", "linked_claimant_email", "created_at"
    },
    "adjuster_decisions": {"id", "claim_id", "decision", "adjuster_username", "decided_at"},
}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create the data directory, upload directory, and tables if missing."""
    DATA_DIR.mkdir(exist_ok=True)
    UPLOADS_DIR.mkdir(exist_ok=True)
    with _connect() as conn:
        for table, expected_columns in _STALE_SCHEMA_TABLES.items():
            existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            if existing and existing != expected_columns:
                conn.execute(f"DROP TABLE {table}")

        conn.executescript(SCHEMA)
        existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(claims)")}
        for statement in _MIGRATIONS:
            if "claimant_email" in statement and "claimant_email" in existing_columns:
                continue
            conn.execute(statement)


def reset() -> None:
    """Wipe all rows (tests only) -- schema stays, data doesn't.

    Children before parents: every table referencing claims(claim_id) has to
    be cleared before claims itself, or the foreign-key constraint rejects
    the DELETE.
    """
    with _connect() as conn:
        conn.execute("DELETE FROM adjuster_decisions")
        conn.execute("DELETE FROM status_history")
        conn.execute("DELETE FROM documents")
        conn.execute("DELETE FROM claim_facts")
        conn.execute("DELETE FROM claim_summaries")
        conn.execute("DELETE FROM notifications")
        conn.execute("DELETE FROM claims")
        conn.execute("DELETE FROM users")
        conn.execute("DELETE FROM adjusters")
        conn.execute("DELETE FROM login_events")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save_uploaded_file(claim_id: str, filename: str, content: bytes) -> Path:
    """Write uploaded bytes to data/uploads/<claim_id>/<filename> and return the path.

    Strips any directory component from the filename (defends against a
    crafted filename like "../../etc/passwd") and de-duplicates a name that
    already exists for this claim by appending a numeric suffix.
    """
    safe_name = Path(filename).name or "unnamed_file"
    claim_dir = UPLOADS_DIR / claim_id
    claim_dir.mkdir(parents=True, exist_ok=True)

    target = claim_dir / safe_name
    if target.exists():
        stem, suffix = Path(safe_name).stem, Path(safe_name).suffix
        counter = 2
        while target.exists():
            target = claim_dir / f"{stem}-{counter}{suffix}"
            counter += 1

    target.write_bytes(content)
    return target


def get_or_create_user(email: str, name: str | None) -> dict:
    """Look up a user by email, creating one on first login.

    This is the "creates an account behind the scenes" step: nothing about
    signing in with Google requires a separate sign-up flow -- the first
    successful login *is* the account creation.
    """
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if row is not None:
            return dict(row)
        conn.execute(
            "INSERT INTO users (email, name, created_at) VALUES (?, ?, ?)",
            (email, name, _now()),
        )
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return dict(row)


def get_user(email: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return dict(row) if row else None


def _hash_password(password: str, salt_hex: str) -> str:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1
    ).hex()


def create_adjuster(username: str, name: str | None = None, linked_claimant_email: str | None = None) -> str:
    """Provision an adjuster account with a random password.

    There is no sign-up route for this -- it's meant to be run by hand (see
    README), the same way an insurer would provision credentials for someone
    who has actually cleared a real state adjuster license, not just typed in
    an email address. Returns the plaintext password exactly once; only its
    salted scrypt hash is ever stored.

    `linked_claimant_email` is optional and exists purely for the separation-
    of-duties check in app.py's decision endpoint: if the same real person
    also has a claimant account (unusual, but our own test accounts do this),
    recording that link lets the app refuse to let them decide on a claim
    they filed themselves. Leave it unset for an adjuster with no claimant
    account at all -- there's nothing to conflict with.
    """
    password = secrets.token_urlsafe(12)
    salt = secrets.token_hex(16)
    password_hash = _hash_password(password, salt)
    with _connect() as conn:
        conn.execute(
            """INSERT INTO adjusters
               (username, password_hash, salt, name, linked_claimant_email, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (username, password_hash, salt, name, linked_claimant_email, _now()),
        )
    return password


def verify_adjuster(username: str, password: str) -> dict | None:
    """Check a login attempt. Returns the adjuster record on success, else None.

    Uses `hmac.compare_digest` rather than `==` so a failed check takes the
    same amount of time regardless of where the mismatch occurs -- a regular
    string comparison leaks timing information an attacker could use to guess
    the hash byte by byte.
    """
    with _connect() as conn:
        row = conn.execute("SELECT * FROM adjusters WHERE username = ?", (username,)).fetchone()
    if row is None:
        return None
    candidate = _hash_password(password, row["salt"])
    if not hmac.compare_digest(candidate, row["password_hash"]):
        return None
    return {
        "username": row["username"],
        "name": row["name"],
        "linked_claimant_email": row["linked_claimant_email"],
    }


def get_adjuster(username: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT username, name, linked_claimant_email, created_at FROM adjusters WHERE username = ?",
            (username,),
        ).fetchone()
        return dict(row) if row else None


def create_claim(
    claim_id: str,
    claimant_email: str,
    policy_id: str,
    incident_date: str,
    description: str,
    status: str,
    missing: list[str],
) -> None:
    now = _now()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO claims
               (claim_id, claimant_email, policy_id, incident_date, description, status, missing, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (claim_id, claimant_email, policy_id, incident_date, description, status, json.dumps(missing), now),
        )
        conn.execute(
            "INSERT INTO status_history (claim_id, status, at) VALUES (?, ?, ?)",
            (claim_id, status, now),
        )


def add_decision(claim_id: str, decision: str, adjuster_username: str) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO adjuster_decisions (claim_id, decision, adjuster_username, decided_at)
               VALUES (?, ?, ?, ?)""",
            (claim_id, decision, adjuster_username, _now()),
        )


def add_document(
    claim_id: str,
    filename: str,
    stored_path: Path,
    content_type: str | None,
    size_bytes: int,
) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO documents
               (claim_id, filename, stored_path, content_type, size_bytes, uploaded_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (claim_id, filename, str(stored_path), content_type, size_bytes, _now()),
        )


def _row_to_record(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    documents = conn.execute(
        "SELECT filename, content_type, size_bytes, uploaded_at FROM documents "
        "WHERE claim_id = ? ORDER BY id",
        (row["claim_id"],),
    ).fetchall()
    history = conn.execute(
        "SELECT status, at FROM status_history WHERE claim_id = ? ORDER BY id",
        (row["claim_id"],),
    ).fetchall()
    decisions = conn.execute(
        "SELECT decision, adjuster_username, decided_at FROM adjuster_decisions "
        "WHERE claim_id = ? ORDER BY id",
        (row["claim_id"],),
    ).fetchall()
    facts = conn.execute(
        "SELECT field, value, source, extracted_at FROM claim_facts "
        "WHERE claim_id = ? ORDER BY id",
        (row["claim_id"],),
    ).fetchall()
    summaries = conn.execute(
        "SELECT summary_text, generated_at FROM claim_summaries "
        "WHERE claim_id = ? ORDER BY id DESC LIMIT 1",
        (row["claim_id"],),
    ).fetchall()

    return {
        "claim": {
            "claim_id": row["claim_id"],
            "claimant_email": row["claimant_email"],
            "policy_id": row["policy_id"],
            "incident_date": row["incident_date"],
            "description": row["description"],
            "documents": [d["filename"] for d in documents],
        },
        "status": row["status"],
        "missing": json.loads(row["missing"]),
        "history": [dict(h) for h in history],
        "documents": [dict(d) for d in documents],
        "decisions": [dict(d) for d in decisions],
        "facts": [dict(f) for f in facts],
        "summary": dict(summaries[0]) if summaries else None,
    }


def get_claim(claim_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM claims WHERE claim_id = ?", (claim_id,)).fetchone()
        if row is None:
            return None
        return _row_to_record(conn, row)


def get_document_path(claim_id: str, filename: str) -> Path | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT stored_path FROM documents WHERE claim_id = ? AND filename = ?",
            (claim_id, filename),
        ).fetchone()
    if row is None:
        return None
    path = Path(row["stored_path"])
    return path if path.exists() else None


def list_claims() -> list[dict]:
    """All claims, regardless of owner -- for the adjuster queue only."""
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM claims ORDER BY created_at DESC").fetchall()
        return [_row_to_record(conn, row) for row in rows]


def list_claims_for(claimant_email: str) -> list[dict]:
    """Only the claims a specific claimant submitted -- the privacy boundary
    for the "My Claims" list."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM claims WHERE claimant_email = ? ORDER BY created_at DESC",
            (claimant_email,),
        ).fetchall()
        return [_row_to_record(conn, row) for row in rows]


def record_login_event(role: str, identifier: str, event: str) -> None:
    """Append-only login/logout audit trail.

    `role` is "claimant" or "adjuster"; `identifier` is the email or username;
    `event` is "login" or "logout". This is a record of activity, not a
    session store -- the actual session that decides who's logged in still
    lives in the signed cookie (see auth.py). Nothing here is ever updated or
    deleted, same pattern as status_history and adjuster_decisions.
    """
    with _connect() as conn:
        conn.execute(
            "INSERT INTO login_events (role, identifier, event, at) VALUES (?, ?, ?, ?)",
            (role, identifier, event, _now()),
        )


def list_login_events(identifier: str | None = None) -> list[dict]:
    """The audit trail, optionally filtered to one email/username."""
    with _connect() as conn:
        if identifier is None:
            rows = conn.execute("SELECT * FROM login_events ORDER BY id DESC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM login_events WHERE identifier = ? ORDER BY id DESC", (identifier,)
            ).fetchall()
        return [dict(row) for row in rows]


def add_facts(claim_id: str, facts: list[dict]) -> None:
    """Store extracted facts. Each item is {"field", "value", "source"}.

    Append-only like everything else here -- re-running extraction adds a new
    batch rather than overwriting the last one, so there's a history of what
    extraction produced and when, not just the current answer.
    """
    now = _now()
    with _connect() as conn:
        conn.executemany(
            "INSERT INTO claim_facts (claim_id, field, value, source, extracted_at) VALUES (?, ?, ?, ?, ?)",
            [(claim_id, f["field"], f["value"], f["source"], now) for f in facts],
        )


def add_summary(claim_id: str, summary_text: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO claim_summaries (claim_id, summary_text, generated_at) VALUES (?, ?, ?)",
            (claim_id, summary_text, _now()),
        )


def add_notification(claim_id: str, claimant_email: str, channel: str, message: str) -> None:
    """Record a notification. `channel` is "in_app" or "email".

    Neither channel actually delivers anything -- there's no SMTP call, no
    push service. This is the same mock-outbox pattern used elsewhere in the
    class (an append-only log standing in for a real delivery system), kept
    honest by never claiming to have sent anything.
    """
    with _connect() as conn:
        conn.execute(
            """INSERT INTO notifications (claim_id, claimant_email, channel, message, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (claim_id, claimant_email, channel, message, _now()),
        )


def list_notifications_for(claimant_email: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM notifications WHERE claimant_email = ? ORDER BY id DESC",
            (claimant_email,),
        ).fetchall()
        return [dict(row) for row in rows]


def unread_notification_count_for(claimant_email: str) -> int:
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM notifications WHERE claimant_email = ? AND read_at IS NULL",
            (claimant_email,),
        ).fetchone()
        return row["n"]


def mark_notifications_read(claimant_email: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE notifications SET read_at = ? WHERE claimant_email = ? AND read_at IS NULL",
            (_now(), claimant_email),
        )


def claims_needing_adjuster_attention() -> list[dict]:
    """READY_FOR_REVIEW claims with no decision yet -- the adjuster-side
    "in-app notifications" view. Deliberately not a stored, per-adjuster
    notification feed (that would need tracking what each adjuster has
    already seen, which this app has no concept of yet) -- it's a live,
    derived count computed fresh each time, which is simpler and can't go
    stale the way a stored "unread" flag could.
    """
    with _connect() as conn:
        rows = conn.execute(
            """SELECT c.* FROM claims c
               WHERE c.status = 'READY_FOR_REVIEW'
               AND NOT EXISTS (SELECT 1 FROM adjuster_decisions d WHERE d.claim_id = c.claim_id)
               ORDER BY c.created_at ASC"""
        ).fetchall()
        return [_row_to_record(conn, row) for row in rows]
