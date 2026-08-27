"""Load the season-level reference enrichment for the two modelled teams.

Idempotent: safe to run after `bootstrap.py`. Requires the schema (006) to be
migrated, which `connect()`+`migrate()` in bootstrap already handles; this runs
migrate() too so it also works standalone.
"""
import sys, pathlib, json
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from nbadb.db import connect, migrate
from nbadb.ingest.reference import ingest_enrichment

con = connect()
migrate(con)
doc = json.loads((ROOT / "data" / "enrichment_2025_26.json").read_text())
print("enrichment loaded:", ingest_enrichment(con, doc))
