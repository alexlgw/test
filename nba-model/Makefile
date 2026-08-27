PYTHON ?= python3

.PHONY: rebuild build verify clean

# Full pipeline: fresh DB, run migrations, load the real game, then verify.
rebuild: clean build verify

# Create the DB, apply migrations, seed reference rows, ingest the fixture game.
build:
	$(PYTHON) scripts/bootstrap.py

# Demonstrate replay, integrity checks, and derived views against the loaded DB.
verify:
	$(PYTHON) scripts/verify.py

# Remove the rebuildable database artifact.
clean:
	rm -f data/nba.db data/nba.db-wal data/nba.db-shm
