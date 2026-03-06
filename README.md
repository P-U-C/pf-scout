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
# Run the interactive wizard (recommended for first-time setup)
pf-scout wizard
```

Or set up manually:

```bash
# Initialize workspace (creates ~/.pf-scout/, contacts.db, .gitignore)
pf-scout init

# Add a contact manually
pf-scout add "Allen Day" --identifier github:allenday

# Seed from a GitHub org (discovers + collects all contributors)
pf-scout seed github --org postfiatorg --token $GITHUB_TOKEN

# Seed from Post Fiat leaderboard
export PF_JWT_TOKEN=your-jwt-token
pf-scout seed postfiat

# Generate a prospect pipeline (live mode — no DB needed)
pf-scout prospect --jwt $PF_JWT_TOKEN --output prospects.md

# Generate from stored DB data
pf-scout prospect --from-db --output prospects.md

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
| `pf-scout wizard` | Interactive setup wizard (recommended) |
| `pf-scout init` | Initialize workspace |
| `pf-scout add` | Add a contact with identifiers |
| `pf-scout link` | Link two identifiers to same contact |
| `pf-scout show` | Display contact card |
| `pf-scout list` | List contacts with optional tier filter |
| `pf-scout seed github` | Seed contacts from GitHub org |
| `pf-scout seed postfiat` | Seed contacts from PF leaderboard |
| `pf-scout prospect` | Generate scored prospect pipeline doc |
| `pf-scout update` | Re-collect signals + score interactively |
| `pf-scout report` | Generate markdown/CSV report |
| `pf-scout doctor` | Diagnostic: DB integrity, env vars, rubric |
| `pf-scout export` | Export contacts to JSON |
| `pf-scout set-context` | Set your PF Context as the scoring lens |
| `pf-scout rerank` | Re-rank contacts by context fit (read-only) |
| `--version` | Show version |

## Rubrics

Rubrics are YAML files defining scoring dimensions. See `rubrics/b1e55ed.yaml` for the b1e55ed producer fit rubric.

## PF Context Integration

pf-scout is a native participant in the Post Fiat closed loop. Every PF user has a Context document (`/context` on tasknode) containing their stated **Value**, **Strategy**, and **Tactics** — the protocol's source of truth for identity and intent.

### Set your Context as the scoring lens

```bash
# Pull your own PF Context from tasknode
pf-scout set-context --cookie "$PF_SESSION_COOKIE"

# Or from a local file
pf-scout set-context --file my-context.md
```

Your Context becomes the ranking filter: your stated gaps and priorities determine who floats to the top.

### Collect prospect Contexts

```bash
# Re-collect all signals including PF Context for each prospect
pf-scout update --all --cookie "$PF_SESSION_COOKIE" --rubric rubrics/b1e55ed.yaml
```

Each prospect's Context is content-addressed — a new signal is only stored when their document changes.

### Re-rank by context fit

```bash
# Re-rank all contacts against your current Context (no re-collection)
pf-scout rerank --rubric rubrics/b1e55ed.yaml

# Filter to top tier only
pf-scout rerank --rubric rubrics/b1e55ed.yaml --tier top

# JSON output for piping
pf-scout rerank --format json | jq '.[] | .label'
```

### The closed loop

```
1. pf-scout set-context        → your gaps become the lens
2. pf-scout update --all       → fetch each prospect's Context
3. pf-scout rerank             → ranked by fit to your needs
4. Reach out to top contacts
5. They update their Context   → next update cycle picks it up
6. Your context evolves        → pf-scout set-context → rerank
```

Contact cards (`pf-scout show`) include the prospect's Value/Strategy/Tactics and keyword alignment against your Context.

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
