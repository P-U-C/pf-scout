# pf-scout

Contact intelligence database for Post Fiat contributor recruitment.

Maintains a **persistent, growing profile** for each contact — every signal run appends data, scores are snapshotted, drift is visible over time.

## Install

```bash
pip install pf-scout
# or from source:
git clone https://github.com/P-U-C/pf-scout && cd pf-scout
pip install -e .
```

## Quick start

```bash
# Initialize workspace (creates ~/.pf-scout/, contacts.db, .gitignore)
pf-scout init

# Add a contact manually
pf-scout add "Allen Day" --identifier github:allenday

# Seed from a GitHub org (discovers + collects all contributors)
pf-scout seed github --org postfiatorg --token $GITHUB_TOKEN

# View a contact card
pf-scout show github:allenday

# Score a contact against a rubric
pf-scout update github:allenday --rubric rubrics/b1e55ed.yaml

# List top-tier contacts
pf-scout list --tier top --rubric rubrics/b1e55ed.yaml

# Generate a report
pf-scout report --rubric rubrics/b1e55ed.yaml --output prospects.md
```

## Commands

| Command | Description |
|---------|-------------|
| `pf-scout init` | Initialize workspace |
| `pf-scout add` | Add a contact with identifiers |
| `pf-scout link` | Link two identifiers to same contact |
| `pf-scout show` | Display contact card |
| `pf-scout list` | List contacts with optional tier filter |
| `pf-scout seed github` | Seed contacts from GitHub org |
| `pf-scout update` | Re-collect signals + score interactively |
| `pf-scout report` | Generate markdown/CSV report |
| `pf-scout doctor` | Diagnostic: DB integrity, env vars, rubric |
| `pf-scout export` | Export contacts to JSON |
| `--version` | Show version |

## Rubrics

Rubrics are YAML files defining scoring dimensions. See `rubrics/b1e55ed.yaml` for the b1e55ed producer fit rubric.

## Privacy

- DB is gitignored by default on `pf-scout init`
- Session cookies and API tokens are **never stored** in the database
- `pf-scout export --anonymize` strips all identifying fields

## Architecture

- SQLite-backed, single file (`~/.pf-scout/contacts.db`)
- Append-only signal log — no data is ever overwritten
- Pluggable collectors (GitHub included; PostFiat, Twitter in v2)
- Manual/assisted scoring in v1; auto-scoring in v2

See [SPEC.md](SPEC.md) for full product specification.

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -q
```

## License

MIT
