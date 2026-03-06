# Privacy Model

pf-scout is local-first. The database is never sent anywhere by default.

## Field tiers

| Tier | Examples | Exported by default |
|------|---------|---------------------|
| public | GitHub handle, commit count | ✅ Yes |
| derived | Scores, tiers, totals | ✅ Yes |
| private | Manual notes, real names | ❌ No |
| secrets | API tokens, cookies | Never stored |

## Export modes

```bash
# Default: public + derived only
pf-scout export --output prospects.json

# Include private notes
pf-scout export --include-private --output full.json

# Anonymized: no handles, no labels
pf-scout export --anonymize --output share.json
```

## Credentials

API tokens and session cookies are **never stored** in the database. Pass at runtime:
```bash
export GITHUB_TOKEN=ghp_...
export PF_SESSION_COOKIE="..."
pf-scout update --all
```
