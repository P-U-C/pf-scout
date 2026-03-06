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

## PostFiat (bundled)

Collects: `postfiat/context`

```bash
export PF_SESSION_COOKIE="your-tasknode-session-cookie"
pf-scout update github:allenday --cookie "$PF_SESSION_COOKIE"
```

Auth: Tasknode session cookie. Get it from your browser: F12 → Application → Cookies → tasknode.postfiat.org → copy the session cookie value.

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
