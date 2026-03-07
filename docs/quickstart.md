# Quickstart

## Option A: Wizard (recommended)

```bash
pf-scout wizard
```

Guides you through workspace init, GitHub token, seeding, PF Context setup, and rubric selection in ~2 minutes.

## Option B: Manual setup

## 1. Initialize
```bash
pf-scout init
```
Creates `~/.pf-scout/contacts.db` and a `.gitignore` so the DB is never accidentally committed.

## 2. Seed from GitHub
```bash
export GITHUB_TOKEN=ghp_...
pf-scout seed github --org postfiatorg
```
Discovers all org contributors, creates contact records, and collects profile + commit signals.

## 3. Seed from Post Fiat leaderboard
```bash
export PF_JWT_TOKEN=your-jwt-token
pf-scout seed postfiat
# Optional filters:
pf-scout seed postfiat --min-alignment 70 --min-monthly-pft 50000
```
Fetches all contributors from the PF leaderboard API, creates contact records, and stores leaderboard signals.

## 4. Generate a prospect pipeline
```bash
# Live mode (fetches leaderboard directly, no DB needed)
pf-scout prospect --jwt $PF_JWT_TOKEN --output prospects.md

# DB mode (uses stored signals from seed postfiat)
pf-scout prospect --from-db --output prospects.md

# Custom rubric
pf-scout prospect --rubric rubrics/pf-default.yaml --jwt $PF_JWT_TOKEN --output prospects.md
```

## 5. View a contact
```bash
pf-scout show github:allenday
```

## 4. Score manually
```bash
pf-scout update github:allenday --rubric rubrics/b1e55ed.yaml
```
Presents each rubric dimension with evidence, prompts for a score (1–5).

## 5. Set your PF Context (optional but recommended)

```bash
export PF_SESSION_COOKIE="your-tasknode-session-cookie"
pf-scout set-context --cookie "$PF_SESSION_COOKIE"
```

Your Context document from Post Fiat becomes the scoring lens — contacts whose stated tactics align with your gaps rank higher.

## 6. Re-rank by context fit

```bash
pf-scout rerank --rubric rubrics/b1e55ed.yaml
```

Read-only — no re-collection. Re-ranks everyone against your current Context.

## 7. Generate a report

```bash
pf-scout report --rubric rubrics/b1e55ed.yaml --tier top --output top-prospects.md
```

## 8. List your contacts

```bash
pf-scout list --limit 10
pf-scout list --tier top
```

## 9. Export for backup

```bash
pf-scout export --output backup.json
```

## 10. Track score changes

```bash
pf-scout diff github:someuser
```
