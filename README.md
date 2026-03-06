# pf-scout

Contact intelligence CLI for Post Fiat contributor recruitment.

## Install

```bash
pip install -e .
```

## Quick Start

```bash
# Initialize database
pf-scout init

# Add a contact manually
pf-scout add allenday --identifier github:allenday --identifier wallet:rXXX

# Link two identifiers to the same contact
pf-scout link github:allenday wallet:rXXX --confidence 0.95

# View a contact card
pf-scout show github:allenday
pf-scout show github:allenday --format json
pf-scout show github:allenday --signals --history

# Seed contacts from a GitHub org
export GITHUB_TOKEN=ghp_xxx
pf-scout seed github --org post-fiat-foundation

# Update signals for a contact
pf-scout update github:allenday

# Update with scoring rubric (interactive)
pf-scout update github:allenday --rubric rubrics/b1e55ed.yaml

# Batch update all contacts
pf-scout update --all --rubric rubrics/b1e55ed.yaml --batch

# Dry run (no writes)
pf-scout update github:allenday --dry-run
```

## Custom DB Path

```bash
pf-scout --db /path/to/contacts.db init
# or
export PF_SCOUT_DB=/path/to/contacts.db
```

## Architecture

- **SQLite** with WAL mode for concurrent reads
- **Click** CLI framework
- **Collectors** — pluggable signal sources (GitHub implemented)
- **Rubrics** — YAML-based scoring dimensions
- **Fingerprints** — SHA-256 deduplication for idempotent signal collection

## Testing

```bash
pip install pytest
python -m pytest tests/ -q
```
