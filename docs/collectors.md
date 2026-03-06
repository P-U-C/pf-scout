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
