.PHONY: init verify test clean
init:    ; python3 scripts/bootstrap.py
verify:  ; python3 scripts/verify.py
test:    ; python3 -m pytest tests -q
clean:   ; rm -f data/nba.db data/nba.db-wal data/nba.db-shm
rebuild: clean init verify
