"""Load the ESPN odds fixture into market_line (offline, idempotent).

Requires the games to be loaded first (load_espn.py), since odds attach to games.
"""
import sys, pathlib, json
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from nbadb.db import connect, migrate
from nbadb.ingest.odds import ingest_odds

con = connect()
migrate(con)
doc = json.loads((ROOT / "data" / "espn_odds_2025_26.json").read_text())
print("odds loaded:", ingest_odds(con, doc))
