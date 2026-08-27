.PHONY: init enrich load-espn load-odds verify matchup quarters walkforward odds \
        strategies fetch-espn fetch-odds test clean
init:        ; python3 scripts/bootstrap.py
enrich:      ; python3 scripts/enrich.py
load-espn:   ; python3 scripts/load_espn.py
load-odds:   ; python3 scripts/load_odds.py
verify:      ; python3 scripts/verify.py
matchup:     ; python3 scripts/matchup.py
quarters:    ; python3 scripts/quarters.py
walkforward: ; python3 scripts/walkforward.py
odds:        ; python3 scripts/odds.py
strategies:  ; python3 scripts/strategies.py
fetch-espn:  ; python3 scripts/fetch_espn.py   # NETWORK: refresh the games fixture
fetch-odds:  ; python3 scripts/fetch_odds.py   # NETWORK: refresh the odds fixture
test:        ; python3 -m pytest tests -q
clean:       ; rm -f data/nba.db data/nba.db-wal data/nba.db-shm
rebuild: clean init enrich load-espn load-odds verify
