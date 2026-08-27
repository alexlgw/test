"""Create the DB, seed reference rows, load the real BOS/OKC game, verify."""
import sys, pathlib, json
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from nbadb.db import connect, migrate
from nbadb.ingest.feed import ingest_game_stats

con = connect()
print("migrations applied:", migrate(con))

con.execute("INSERT OR IGNORE INTO season(season_id,label,start_date,end_date) "
            "VALUES (2025,'2025-26','2025-10-21','2026-06-14')")
for c in ("PRE", "REG", "PLAYIN", "PLAYOFF"):
    con.execute("INSERT OR IGNORE INTO season_phase(code) VALUES (?)", (c,))
for code, disp, cls, lic in [("pinnacle", "Pinnacle", "sharp", 0),
                             ("draftkings", "DraftKings", "soft", 1),
                             ("fanduel", "FanDuel", "soft", 1),
                             ("betmgm", "BetMGM", "soft", 1),
                             ("kalshi", "Kalshi", "exchange", 1)]:
    con.execute("INSERT OR IGNORE INTO book(code,display_name,class,is_licensed_us) "
                "VALUES (?,?,?,?)", (code, disp, cls, lic))
con.commit()

payload = json.loads((ROOT / "data" / "bos_okc_raw.json").read_text())
rep = ingest_game_stats(con, payload, "f64ce711-2904-4117-8767-6dbed5ee257e",
                        2025, "2026-03-25T23:30:00Z", "REG")
print("ingested:", rep)
