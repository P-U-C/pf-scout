# pf-scout — Product Specification v1

> **Status**: RFC — seeking review before implementation  
> **Author**: zoz (@zozDOTeth) / b1e55ed  
> **Repo**: https://github.com/P-U-C/pf-scout

---

## 1. Problem

Post Fiat has a growing contributor base spread across GitHub, Discord, on-chain task history, and Twitter/X. There is no persistent, queryable record of who these contributors are, what their skills look like, or how their engagement evolves over time.

When b1e55ed reaches its meta-producer gate, the recruitment process will depend on having a maintained, pre-scored pipeline — not a one-time snapshot. Contributors change. A person who was speculative six months ago may have shipped five infrastructure projects since. A highly-scored prospect may have gone quiet.

There is also a broader need: any Post Fiat node operator building a specialist product (a research node, a trading intelligence node, a governance node) faces the same recruitment problem against the same contributor base. They need to define their own fit criteria and score against them.

**pf-scout** is a contact intelligence database that solves this for b1e55ed first, then for the PF network broadly.

---

## 2. Core Concept

pf-scout maintains a **persistent, growing profile** for each contact. Every signal collection run appends new data rather than overwriting. Scores are snapshotted at each run, so drift is visible over time.

The mental model is a CRM crossed with a signal log:

- **Contact** — the persistent identity record (handle, display name, source, metadata)
- **Signal** — a discrete, timestamped piece of evidence (a commit, a task completion, a Discord message, a tweet)
- **Snapshot** — a point-in-time scoring of a contact against a rubric
- **Note** — free-text annotation, manual or system-generated

Contacts are **never deleted**. Old signals are never overwritten. The picture only grows.

---

## 3. Architecture

### 3.1 Storage

SQLite. Single file, portable, no server dependency. Default path: `~/.pf-scout/contacts.db`. Overridable via `--db` flag or `PF_SCOUT_DB` env var.

The database is designed to be committed to a private git repo for team sharing and audit history, or kept local for personal use.

```sql
-- Core identity
CREATE TABLE contacts (
    handle          TEXT PRIMARY KEY,
    display_name    TEXT,
    first_seen      TEXT NOT NULL,   -- ISO8601
    last_updated    TEXT NOT NULL,
    sources         TEXT NOT NULL,   -- JSON array: ["github", "postfiat", "manual"]
    current_tier    TEXT,            -- cached from latest snapshot
    current_score   REAL,            -- cached from latest snapshot
    tags            TEXT,            -- JSON array of free-form tags
    archived        INTEGER DEFAULT 0  -- soft-delete
);

-- Append-only signal log
CREATE TABLE signals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    handle          TEXT NOT NULL REFERENCES contacts(handle),
    collected_at    TEXT NOT NULL,   -- when pf-scout collected this
    signal_ts       TEXT,            -- when the signal originally occurred (if known)
    source          TEXT NOT NULL,   -- "github", "postfiat", "twitter", "discord", "manual"
    signal_type     TEXT NOT NULL,   -- "commit", "pf_task", "pf_capability", "tweet", "discord_msg"
    payload         TEXT NOT NULL,   -- JSON: source-specific data
    evidence_note   TEXT             -- human-readable summary
);

-- Point-in-time scoring snapshots
CREATE TABLE snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    handle          TEXT NOT NULL REFERENCES contacts(handle),
    snapshot_ts     TEXT NOT NULL,
    rubric_name     TEXT NOT NULL,
    rubric_version  TEXT,
    trigger         TEXT,            -- "manual", "scheduled", "seed"
    dimension_scores TEXT NOT NULL,  -- JSON: {dim_id: score}
    dimension_evidence TEXT,         -- JSON: {dim_id: evidence_note}
    total_score     REAL NOT NULL,
    weighted_score  REAL NOT NULL,
    tier            TEXT NOT NULL
);

-- Free-text annotations
CREATE TABLE notes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    handle          TEXT NOT NULL REFERENCES contacts(handle),
    note_ts         TEXT NOT NULL,
    author          TEXT DEFAULT 'system',  -- 'system' or 'manual'
    body            TEXT NOT NULL
);
```

### 3.2 Collectors (Pluggable)

Each collector is a Python module implementing a simple interface:

```python
class BaseCollector:
    name: str        # "github", "postfiat", "twitter", etc.
    
    def collect(self, handle: str, **kwargs) -> list[Signal]:
        """Return new signals for this handle. Called on update."""
        ...
    
    def discover(self, **kwargs) -> list[str]:
        """Return a list of handles to seed (optional — for bulk discovery)."""
        ...
```

**Bundled collectors:**

| Collector | Discovers | Collects | Auth |
|-----------|-----------|----------|------|
| `github` | Org contributors | Commits, repos, bio, company | Personal access token |
| `postfiat` | Leaderboard, activity channel | Capabilities, Expert Knowledge, task count, PFT earned | Session cookie |
| `twitter` | — | Follower count, bio, keyword analysis | Bearer token |
| `discord` | — | Message frequency, channel participation | Export file |
| `manual` | CSV/JSON | Any field | None |

**Adding a custom collector**: implement `BaseCollector`, register it in `pf_scout/collectors/__init__.py`. No other changes required.

### 3.3 Scoring Engine

Rubrics are YAML files. A rubric defines:
- Named dimensions with weights
- Score guides (1–5 descriptions)
- Auto-scoring hints (which signals map to which dimension)
- Tier thresholds

The scorer applies a rubric to a contact's current signal set and produces a snapshot. Scores are deterministic given the same signal set + rubric version, enabling meaningful diff comparison between runs.

**Manual score overrides** are supported per-dimension per-contact and are stored as signals of type `"manual_score"`.

### 3.4 CLI

```
pf-scout seed    -- bootstrap contacts from a source
pf-scout add     -- add a single contact manually
pf-scout update  -- re-collect signals and re-score
pf-scout show    -- display full contact card
pf-scout note    -- add a manual note to a contact
pf-scout report  -- generate ranked markdown/CSV output
pf-scout diff    -- compare two snapshots for a contact
pf-scout archive -- soft-delete a contact (data preserved)
pf-scout export  -- dump full database to JSON
```

See Section 5 for detailed command signatures.

---

## 4. Data Model — Key Design Decisions

### 4.1 Append-Only Signals

Every discrete piece of evidence is a row in `signals`. Re-running a collector never modifies existing rows; it only inserts new ones (deduped by payload hash). This means:
- Full provenance: you can replay the history of what was known about a contact at any point
- No silent overwrites: if a collector returns different data next month, both versions are preserved
- Diffable: `pf-scout diff` compares snapshots to show what changed

### 4.2 Snapshot-Based Scoring

Scores are never stored on the contact record directly (except as a cache). Every scoring run creates a new snapshot. This means:
- Score drift is visible over time without any extra work
- Rubric changes don't silently corrupt historical scores (old snapshots retain their rubric version)
- A contact can be scored against multiple rubrics simultaneously (e.g., b1e55ed producer fit AND research node fit)

### 4.3 Pseudonymity First

pf-scout operates on handles and wallet addresses, not real identities. The `contacts` table has no name field — only `display_name` which may be a pseudonym, AI-generated moniker, or left null. This mirrors how the Post Fiat platform itself works.

Real identity information should never be committed to the database unless the contact has made it public. The `notes` field is the appropriate place for any identity linkage, kept local and not exported by default.

### 4.4 Composability

pf-scout is designed to work beyond Post Fiat. Any operator building on any network can:
1. Write a collector for their network's data source
2. Define a rubric for their specific fit criteria
3. Run pf-scout against their own contact list

The Post Fiat platform collector is one collector among many. There is no hard dependency on it.

---

## 5. CLI — Detailed Signatures

```bash
# Bootstrap from a source
pf-scout seed github --org postfiatorg --token $GITHUB_TOKEN
pf-scout seed postfiat --cookie "$PF_SESSION_COOKIE" --base-url https://tasknode.postfiat.org
pf-scout seed csv --file prospects.csv

# Add a single contact
pf-scout add allenday --source github --note "Google Cloud blockchain analytics, BigQuery"

# Update signals and re-score (one or all)
pf-scout update allenday --rubric rubrics/b1e55ed.yaml
pf-scout update --all --rubric rubrics/b1e55ed.yaml
pf-scout update --all --rubric rubrics/b1e55ed.yaml --since 7d  # only re-collect if last update >7d ago

# Show full contact card
pf-scout show allenday
pf-scout show allenday --history           # include all snapshots
pf-scout show allenday --signals           # include raw signal log

# Add a note
pf-scout note allenday "Mentioned wanting to build signal producers in Discord 2026-03-06"
pf-scout note allenday --system "Score increased 3pts since last run; PF task count grew from 12→31"

# Generate report
pf-scout report --rubric rubrics/b1e55ed.yaml --output report.md
pf-scout report --rubric rubrics/b1e55ed.yaml --tier top --output top-tier.md
pf-scout report --rubric rubrics/b1e55ed.yaml --format csv --output prospects.csv

# Diff two snapshots
pf-scout diff allenday                     # latest vs previous
pf-scout diff allenday --since 2026-01-01  # latest vs first after date

# Export
pf-scout export --output backup.json      # full database as JSON
pf-scout export allenday                  # single contact
```

---

## 6. Contact Card Format

`pf-scout show allenday` outputs:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  allenday  (Allen Day)                🔴 TOP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Sources:     github, postfiat
  First seen:  2026-03-06
  Last update: 2026-03-06
  Tags:        blockchain-analytics, on-chain-data, infra

  SCORES (b1e55ed.yaml v1.0) — 2026-03-06
  ┌─────────────────────────┬───────┬────────────────────────────────────┐
  │ Dimension               │ Score │ Evidence                           │
  ├─────────────────────────┼───────┼────────────────────────────────────┤
  │ Quantitative Depth      │  5/5  │ PhD human genetics; BigQuery ML    │
  │ Infrastructure Cap.     │  4/5  │ Google Cloud infra; 24 PF commits  │
  │ Market Analysis         │  2/5  │ No market-facing output observed   │
  │ Signal Generation       │  5/5  │ Built public BTC/ETH/XRP datasets  │
  │ Engagement Consistency  │  3/5  │ GitHub active; PF tasks: 0         │
  └─────────────────────────┴───────┴────────────────────────────────────┘
  Weighted: 24.9 / 32.5

  SCORE HISTORY
  2026-03-06  24.9  🔴 TOP  (seed run)

  SIGNALS (most recent 5)
  2026-03-06  github/commit    postfiatorg/.github.io (24 commits)
  2026-03-06  github/profile   bio: PhD. Google Cloud. BigQuery.

  NOTES
  2026-03-06 [system]  Initial seed from postfiatorg GitHub contributors
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 7. Rubric Format (YAML)

```yaml
name: b1e55ed Producer Fit
version: "1.0"
description: >
  Scoring rubric for identifying Post Fiat contributors who could become
  b1e55ed producers, infrastructure contributors, or mechanism reviewers.

dimensions:
  - id: quant_depth
    name: Quantitative Depth
    weight: 1.5
    description: Statistical, ML, or quantitative finance background
    auto_score_hints:
      signals: ["github/profile", "postfiat/capability"]
      keywords: ["quant", "ml", "phd", "statistics", "data science", "algo"]
    score_guide:
      5: "PhD/professional quant, published models, production ML"
      4: "Strong ML/stats, GitHub shows applied quantitative work"
      3: "Engineering-first with quantitative exposure"
      2: "Some data skills, limited quant focus"
      1: "No observable quantitative background"

  - id: infra_capability
    name: Infrastructure Capability
    weight: 1.2
    description: Can build and operate server-side data pipelines and nodes
    auto_score_hints:
      signals: ["github/commit"]
      commit_count_thresholds: [10, 50, 100, 500]
    score_guide:
      5: "Production infra, validators, distributed systems"
      4: "Active DevOps/backend, cloud infra history"
      3: "Can self-host, moderate infra experience"
      2: "Limited infra exposure"
      1: "No observable infrastructure capability"

  - id: market_analysis
    name: Market Analysis / Forecasting
    weight: 1.3
    description: Track record of structured market commentary or analysis
    auto_score_hints:
      signals: ["twitter/profile", "postfiat/task"]
      keywords: ["trader", "portfolio", "macro", "alpha", "market analyst"]
    score_guide:
      5: "Professional trader/PM, published systematic research"
      4: "Regular structured market analysis, verifiable outputs"
      3: "Market-aware, occasional structured analysis"
      2: "Crypto-native, limited analytical depth"
      1: "No market analysis observable"

  - id: signal_generation
    name: Signal Generation History
    weight: 1.4
    description: Has produced data-driven signals from on-chain, market, or social data
    auto_score_hints:
      signals: ["github/profile", "postfiat/capability"]
      keywords: ["signal", "analytics", "bigquery", "pipeline", "etl", "on-chain"]
    score_guide:
      5: "Built production signal pipelines, systematic alpha research"
      4: "ETL/analytics for market or on-chain data"
      3: "Data engineering applicable to signal production"
      2: "Some data work, not signal-focused"
      1: "No signal generation background"

  - id: engagement_consistency
    name: Engagement Consistency
    weight: 1.0
    description: Reliable, sustained engagement with the Post Fiat ecosystem
    auto_score_hints:
      signals: ["github/commit", "postfiat/task"]
      pf_task_thresholds: [5, 20, 50, 100]
    score_guide:
      5: "Core contributor, multi-month, consistent daily/weekly"
      4: "Regular, multiple months verifiable"
      3: "Periodic, engaged when active"
      2: "One-time or sparse"
      1: "Minimal or no verifiable engagement"

tiers:
  top:       { label: "🔴 TOP",         min_pct: 0.64 }
  mid:       { label: "🟡 MID",         min_pct: 0.40 }
  speculative: { label: "⚪ SPECULATIVE", min_pct: 0.0  }
```

---

## 8. Composability Design

### 8.1 Multiple Rubrics Per Contact

A contact can be scored against N rubrics simultaneously. Each produces an independent snapshot tagged with `rubric_name`. This enables:

```bash
pf-scout report --rubric rubrics/b1e55ed.yaml      # b1e55ed producer fit
pf-scout report --rubric rubrics/research-node.yaml # research intelligence fit
pf-scout report --rubric rubrics/infra-node.yaml    # infrastructure fit
```

The contact record shows their best tier across all rubrics in the contact card.

### 8.2 External Data Sources

pf-scout has no opinion on where signals come from. A collector for a private data source (e.g., a proprietary Discord export, an internal HRMS, a Nansen API response) is identical in structure to the bundled GitHub collector. The only requirement: return `Signal` objects.

### 8.3 Network-Agnostic Core

The core (`contacts`, `signals`, `snapshots`, `notes`) has no dependency on Post Fiat. The PF collector is a plugin. Any network with a contributor base can use pf-scout by writing a collector for their data source.

---

## 9. Privacy Considerations

- All data is local by default (SQLite file, no network calls except by collectors)
- Session cookies and API tokens are never stored in the database — only passed at runtime
- No real identity is stored unless the contact has made it public
- Export functions include an `--anonymize` flag that strips display names and notes
- The database should be gitignored if it contains any non-public information

---

## 10. Out of Scope (v1)

- Web UI (CLI first)
- Real-time streaming (batch collection only)
- Automatic outreach integration (the doc is a pipeline, not a dialer)
- Hosted/multi-user mode (local-first, share via git or export)
- On-chain storage of scores (privacy concern; local only for v1)

---

## 11. Open Questions for Review

1. **Schema extensibility**: Should `signals.payload` remain free-form JSON, or should each `signal_type` have a typed schema? Free-form is flexible but harder to query. Typed schemas are more rigid but enable better auto-scoring.

2. **Deduplication strategy**: How should the collector detect that a signal already exists? Current proposal: hash of `(handle, source, signal_type, payload_canonical)`. Is there a better key?

3. **Rubric versioning**: When a rubric changes, old snapshots become incompatible. Should the tool auto-flag snapshots taken with older rubric versions, or silently allow mixed comparisons?

4. **Score decay**: Should engagement dimensions decay over time without new signals (i.e., a contact who was active 2 years ago shouldn't score 5 today)? If so, what's the decay function?

5. **Multi-handle contacts**: A person may have a GitHub handle, a wallet address, and a Twitter handle. Should these be separate contacts (linked by tag/note) or unified under a canonical identity? v1 proposal: separate contacts, linked by tag `alias:other-handle`. Is this sufficient?

6. **Collector auth management**: Session cookies expire. API tokens rotate. Should pf-scout have a secrets manager integration (e.g., env vars, `.env` file, OS keychain), or stay simple and require re-passing at runtime?

---

## 12. Implementation Plan

| Phase | Scope | Status |
|-------|-------|--------|
| v0 (done) | One-shot CSV → score → markdown | ✅ Prototype in workspace |
| v1 | SQLite store, seed/update/show/report CLI, GitHub + manual collectors | 🔲 This spec |
| v2 | Post Fiat platform collector (requires session cookie) | 🔲 Post-spec |
| v3 | Twitter collector, score decay, multi-rubric reports | 🔲 Roadmap |
| v4 | Discord export collector, alert system (score threshold triggers) | 🔲 Roadmap |

---

## Appendix: Example Contact Database State

After initial seed from postfiatorg GitHub + manual entries:

```
Contacts: 17
Signals:  142  (avg 8.3 per contact)
Snapshots: 17  (1 per contact, seed run)
Notes:    22   (mix of system + manual)

Top tier (b1e55ed.yaml v1.0):
  🔴 goodalexander   weighted=28.2  (22/25 raw)
  🔴 allenday        weighted=24.9  (19/25 raw)
  🔴 Citrini7        weighted=23.5  (18/25 raw)
  🔴 Travis          weighted=20.9  (16/25 raw)
  🔴 based16z        weighted=20.5  (16/25 raw)
  🔴 pft-highpft     weighted=20.0  (16/25 raw)
  🔴 DRavlic         weighted=19.5  (16/25 raw)
```
