# Collectors

Collectors gather signals from external platforms.

## GitHub (bundled)

Collects: `github/profile`, `github/commit`

```bash
export GITHUB_TOKEN=ghp_...
pf-scout seed github --org postfiatorg
pf-scout update github:allenday
```

Auth: GitHub Personal Access Token with `read:org` + `read:user` scopes.

## PostFiat Leaderboard (bundled)

Collects: `postfiat/leaderboard`

```bash
export PF_JWT_TOKEN=your-jwt-token
pf-scout seed postfiat
```

Auth: JWT Bearer token from tasknode. Pass via `--jwt` or `PF_JWT_TOKEN` env var.

**API endpoint:** `GET https://tasknode.postfiat.org/api/leaderboard`

**Payload fields:**
- `wallet_address` — XRPL wallet
- `summary` — contributor description
- `capabilities` — list of skills (str or dict)
- `expert_knowledge` — list of `{domain: str}`
- `monthly_rewards`, `weekly_rewards` — PFT earned
- `monthly_tasks` — tasks completed this month
- `alignment_score`, `alignment_tier` — protocol alignment metrics
- `sybil_score`, `sybil_risk` — identity verification confidence
- `leaderboard_score_month`, `leaderboard_score_week` — composite scores
- `is_published`, `user_id` — account metadata

**Dedup:** Content-addressed via event fingerprint. Re-running is safe — only new/changed data creates new signals.

---

## PostFiat Context (bundled)

Collects: `postfiat/context`

```bash
export PF_SESSION_COOKIE="your-tasknode-session-cookie"
pf-scout update github:allenday --cookie "$PF_SESSION_COOKIE"
```

Auth: Tasknode session cookie. Get it from your browser: F12 → Application → Cookies → tasknode.postfiat.org → copy the session cookie value.

**Security note**: The `--base-url` option defaults to `https://tasknode.postfiat.org`. Only override this for local development or testing — passing untrusted user input as `base_url` is an SSRF risk.

**Content-addressed dedup**: A new signal is only stored when the prospect's Context document actually changes. Re-running collection is safe.

**Graceful fallback**: If a prospect's Context is not accessible (auth required), the collector stores a stub signal with `auth_required: true` and the contact card shows a warning rather than failing.

## Writing a custom collector

```python
from pf_scout.collectors.base import BaseCollector, CollectedSignal

class MyCollector(BaseCollector):
    name = "mycollector"
    idempotent = True

    def collect(self, identifier, db, **kwargs) -> list[CollectedSignal]:
        # return list of CollectedSignal objects
        ...

    def discover(self, **kwargs) -> list[tuple[str, str]]:
        # return [(platform, identifier_value), ...]
        ...
```
