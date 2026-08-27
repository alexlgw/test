"""Fetch real opening & closing odds for the 162-game BOS/OKC season from ESPN.

NETWORK STEP (like fetch_espn.py). Reads the event ids from the games fixture,
pulls ESPN's core odds endpoint per game, and writes data/espn_odds_2025_26.json
with the ESPN BET open and close lines for spread, moneyline, and total. The
offline ingest (nbadb.ingest.odds) then loads it into market_line.

ESPN's core odds carry open/close/current for each selection -- the closing line
is the sharp consensus a bet is graded against, which is the number this whole
project has been missing.
"""
import json, subprocess, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
GAMES = ROOT / "data" / "espn_2025_26_games.json"
OUT = ROOT / "data" / "espn_odds_2025_26.json"
CORE = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events"
CA = "/root/.ccr/ca-bundle.crt"
PROVIDER = "ESPN BET"


def get(url, tries=3):
    last = ""
    for _ in range(tries):
        r = subprocess.run(["curl", "-sS", "--retry", "2", "--cacert", CA, url],
                           capture_output=True, text=True)
        if r.returncode == 0:
            try:
                return json.loads(r.stdout)
            except json.JSONDecodeError:
                return None
        last = r.stderr[:150]
    raise RuntimeError(f"curl failed: {url}: {last}")


def am(x):
    """ESPN american value (str/num) -> number. '+240'->240, '-6.5'->-6.5,
    'EVEN'->100, 'OFF'/None->None."""
    if isinstance(x, dict):
        x = x.get("american", x.get("alternateDisplayValue"))
    if x in (None, "", "OFF", "--"):
        return None
    if isinstance(x, str):
        x = x.strip().replace("+", "")
        if x.upper() == "EVEN":
            return 100
    try:
        f = float(x)
        return int(f) if f == int(f) else f
    except (ValueError, TypeError):
        return None


def extract(od):
    prov = {i.get("provider", {}).get("name"): i for i in od.get("items", [])}
    it = prov.get(PROVIDER) or (od["items"][0] if od.get("items") else None)
    if not it:
        return None
    ho, ao = it.get("homeTeamOdds", {}), it.get("awayTeamOdds", {})

    def leg(o, key, sub):
        node = (o.get(key) or {}).get(sub)
        return am(node)

    rec = {
        "provider": it.get("provider", {}).get("name"),
        "favorite": "home" if ho.get("favorite") else ("away" if ao.get("favorite") else None),
        "spread": {
            "open_home": leg(ho, "open", "pointSpread"), "close_home": leg(ho, "close", "pointSpread"),
            "open_away": leg(ao, "open", "pointSpread"), "close_away": leg(ao, "close", "pointSpread"),
            "juice": am(ho.get("spreadOdds")) or -110,
        },
        "moneyline": {
            "open_home": leg(ho, "open", "moneyLine"), "close_home": am(ho.get("moneyLine")) or leg(ho, "close", "moneyLine"),
            "open_away": leg(ao, "open", "moneyLine"), "close_away": am(ao.get("moneyLine")) or leg(ao, "close", "moneyLine"),
        },
        "total": {
            "open": am((it.get("open") or {}).get("total")), "close": am((it.get("close") or {}).get("total")),
            "over_odds": am((it.get("close") or {}).get("over")) or -110,
            "under_odds": am((it.get("close") or {}).get("under")) or -110,
        },
    }
    return rec


def main():
    games = json.loads(GAMES.read_text())["games"]
    out = []
    miss = 0
    for i, g in enumerate(games, 1):
        eid = g["event_id"]
        od = get(f"{CORE}/{eid}/competitions/{eid}/odds")
        rec = extract(od) if od else None
        if not rec:
            miss += 1
            continue
        rec["event_id"] = eid
        rec["home"] = g["home"]["abbr"]
        rec["away"] = g["away"]["abbr"]
        rec["date"] = g["date"]
        out.append(rec)
        if i % 30 == 0:
            print(f"  {i}/{len(games)} fetched", file=sys.stderr)
    OUT.write_text(json.dumps({"season_id": 2025, "provider": PROVIDER,
                               "games": out}, separators=(",", ":")))
    print(f"wrote {OUT.name}: {len(out)} games with odds, {miss} missing, "
          f"{OUT.stat().st_size/1024:.0f} KB", file=sys.stderr)


if __name__ == "__main__":
    main()
