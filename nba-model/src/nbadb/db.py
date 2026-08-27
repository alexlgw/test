"""Connection handling and migrations."""
from __future__ import annotations
import sqlite3, hashlib, pathlib, unicodedata, json, re

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "schema"
DEFAULT_DB = ROOT / "data" / "nba.db"


def connect(path=DEFAULT_DB) -> sqlite3.Connection:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")      # concurrent reads during ingest
    con.execute("PRAGMA synchronous = NORMAL")
    return con


def migrate(con: sqlite3.Connection) -> list[str]:
    """Apply any .sql in schema/ not yet recorded. Idempotent."""
    con.execute("""CREATE TABLE IF NOT EXISTS schema_migration (
        filename TEXT PRIMARY KEY,
        sha256   TEXT NOT NULL,
        applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')))""")
    done = {r["filename"]: r["sha256"] for r in con.execute("SELECT * FROM schema_migration")}
    applied = []
    for f in sorted(SCHEMA_DIR.glob("*.sql")):
        sql = f.read_text()
        digest = hashlib.sha256(sql.encode()).hexdigest()
        if f.name in done:
            if done[f.name] != digest:
                raise RuntimeError(
                    f"{f.name} changed after being applied. Migrations are "
                    f"append-only: add a new numbered file instead of editing.")
            continue
        con.executescript(sql)
        con.execute("INSERT INTO schema_migration(filename,sha256) VALUES (?,?)",
                    (f.name, digest))
        applied.append(f.name)
    con.commit()
    return applied


# ------------------------------------------------------------------ provenance
def land_payload(con, source: str, endpoint: str, request_key: str, obj) -> int:
    """Store a raw response and return its payload_id. Content-addressed, so
    re-landing identical content is free; changed content makes a new row."""
    body = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(body.encode()).hexdigest()
    cur = con.execute(
        "SELECT payload_id FROM raw_payload WHERE source=? AND endpoint=? "
        "AND request_key=? AND body_sha256=?", (source, endpoint, request_key, digest))
    row = cur.fetchone()
    if row:
        return row["payload_id"]
    return con.execute(
        "INSERT INTO raw_payload(source,endpoint,request_key,body,body_sha256) "
        "VALUES (?,?,?,?,?)", (source, endpoint, request_key, body, digest)).lastrowid


# ------------------------------------------------------------------ identity
def norm_name(s: str) -> str:
    """Casefold, strip diacritics and punctuation. 'Luka Dončić' -> 'luka doncic'.
    Deliberately lossy: it is a BLOCKING key for candidate lookup, not an id."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-zA-Z0-9 ]", " ", s).lower()
    return re.sub(r"\s+", " ", s).strip()


def resolve_player(con, source: str, observed: str, position: str | None = None) -> int | None:
    """Map a feed name string to a player_id.

    Returns None when ambiguous — the caller must NOT invent a player. An
    unresolved alias is parked with status='unresolved' and surfaces in the
    check_unresolved_players view for a human to adjudicate. Silently minting
    a new player on every spelling variant is how a stats database rots.
    """
    row = con.execute("SELECT player_id,status FROM player_alias WHERE source=? AND observed_name=?",
                      (source, observed)).fetchone()
    if row and row["status"] == "resolved":
        return row["player_id"]

    key = norm_name(observed)
    cands = con.execute(
        "SELECT player_id FROM player_alias WHERE norm_name=? AND status='resolved' "
        "GROUP BY player_id", (key,)).fetchall()

    if len(cands) == 1:
        pid = cands[0]["player_id"]
        status = "resolved"
    elif len(cands) > 1:
        pid, status = None, "ambiguous"
    else:
        pid = con.execute("INSERT INTO player(full_name,primary_pos) VALUES (?,?)",
                          (observed, position)).lastrowid
        status = "resolved"

    con.execute(
        "INSERT INTO player_alias(source,observed_name,norm_name,player_id,status,resolved_at) "
        "VALUES (?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%SZ','now')) "
        "ON CONFLICT(source,observed_name) DO UPDATE SET player_id=excluded.player_id, "
        "status=excluded.status, resolved_at=excluded.resolved_at",
        (source, observed, key, pid, status))
    return pid
