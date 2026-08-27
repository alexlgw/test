.PHONY: init enrich load-espn verify matchup quarters walkforward fetch-espn test clean
init:        ; python3 scripts/bootstrap.py
enrich:      ; python3 scripts/enrich.py
load-espn:   ; python3 scripts/load_espn.py
verify:      ; python3 scripts/verify.py
matchup:     ; python3 scripts/matchup.py
quarters:    ; python3 scripts/quarters.py
walkforward: ; python3 scripts/walkforward.py
fetch-espn:  ; python3 scripts/fetch_espn.py   # NETWORK: refresh data/espn_2025_26_games.json
test:        ; python3 -m pytest tests -q
clean:       ; rm -f data/nba.db data/nba.db-wal data/nba.db-shm
rebuild: clean init enrich load-espn verify
