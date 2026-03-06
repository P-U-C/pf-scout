# Quickstart

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

## 3. View a contact
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
