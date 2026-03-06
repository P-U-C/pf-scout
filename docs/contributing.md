# Contributing to pf-scout

## Review Council

All PRs targeting `main` are automatically reviewed by the pf-scout Review Council.

The council runs on PR open and sync events. It applies a `review/pending` label, then sends a trigger to the b1e55ed review system. Results are posted as PR comments with one of:

- `review/pass` — approved, ready to merge
- `review/concern` — concerns found, addressed before merge
- `review/block` — blocking issue, must be resolved
- `review/human-required` — sensitive path, human review required

### Sensitive paths (always human-reviewed)
- `pf_scout/db.py` — database connection and schema
- `pf_scout/schema.py` — table definitions
- `pf_scout/collectors/postfiat.py` — external auth handling

### Setup (repo admins)

The review workflow requires two GitHub Actions secrets:
- `TELEGRAM_BOT_TOKEN` — the b1e55ed Telegram bot token
- `TELEGRAM_CHAT_ID` — the b1e55ed operator chat ID

These are already set on P-U-C/b1e55ed and need to be mirrored to P-U-C/pf-scout.
