.PHONY: init enrich verify matchup test clean
init:    ; python3 scripts/bootstrap.py
enrich:  ; python3 scripts/enrich.py
verify:  ; python3 scripts/verify.py
matchup: ; python3 scripts/matchup.py
test:    ; python3 -m pytest tests -q
clean:   ; rm -f data/nba.db data/nba.db-wal data/nba.db-shm
rebuild: clean init enrich verify
