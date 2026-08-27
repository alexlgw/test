"""Load the real ESPN season fixture into the DB (offline, idempotent)."""
import sys, pathlib, json
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from nbadb.db import connect, migrate
from nbadb.ingest.espn import ingest_espn_games

con = connect()
migrate(con)
doc = json.loads((ROOT / "data" / "espn_2025_26_games.json").read_text())
print("espn season loaded:", ingest_espn_games(con, doc))
