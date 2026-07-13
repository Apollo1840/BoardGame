launch:
	python3 scripts/serve.py

serve:
	python3 scripts/serve.py

db-import:
	python3 scripts/import_legacy_data.py --report data/v1.1-import-report.json

cards-import:
	python3 scripts/import_cards.py

cards-import-dry-run:
	python3 scripts/import_cards.py --dry-run

db-dry-run:
	python3 scripts/import_legacy_data.py --dry-run

db-validate:
	python3 scripts/validate_data.py --include-import-errors

db-export:
	python3 scripts/export_legacy_data.py --output data/export

test:
	python3 -m unittest discover -s tests -v
