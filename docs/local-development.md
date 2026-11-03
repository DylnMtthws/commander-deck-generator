# Local development

## Setup

Requires Python 3.11+, disk space for the card corpus and CPU embedding model,
and a Hugging Face Inference Providers credential for actual generation.

```sh
git clone https://github.com/DylnMtthws/commander-deck-generator.git
cd commander-deck-generator
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
python scripts/setup_db.py
python scripts/initial_ingestion.py --scryfall-only
python scripts/setup_db.py --prepare-corpus
export SABER_OWNER_EMAIL=you@example.com
export SABER_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
export SABER_COOKIE_SECURE=0
sabermetrics create-admin --email "$SABER_OWNER_EMAIL"
# Set HF_TOKEN securely in your shell before generating.
sabermetrics serve
```

Open `http://127.0.0.1:5000`. Environment examples are in
[.env.example](../.env.example); a `.env` file is not automatically loaded.
The installed command retains its original `sabermetrics` name. Use a separate
virtual environment from Deck Lab, which retains the same Python import namespace.

```sh
sabermetrics build "Korvold, Fae-Cursed King" --budget 150 --output-format text
sabermetrics profile "Korvold, Fae-Cursed King"
sabermetrics health
```

For richer empirical evidence, run `pull-decks`, `cluster-decks`, and
`value-cards` for the commander. These commands require network access and source
availability. Settings, scoring weights, model IDs, and cost estimates live in
[`config/settings.yaml`](../config/settings.yaml). Configuration ships inside the wheel;
`config/` links to the same packaged files. `SABER_CONFIG_DIR` can supply an explicit
configuration directory. Schema upgrades are additive; public role tagging and
candidate preparation run separately so normal requests do not repeat that work.


## Checks

```sh
pytest -q
ruff check src tests
mypy src
```

Tests and an installed-container smoke are CI gates; lint and types remain report-only.
See [hosting](hosting.md) for deployment and [settings](../config/settings.yaml) for model IDs, configurable cost estimates and spend limits. The usage ledger is an estimate, not a provider billing cap.
