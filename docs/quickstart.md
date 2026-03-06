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

## 5. Generate a report
```bash
pf-scout report --rubric rubrics/b1e55ed.yaml --tier top --output top-prospects.md
```
