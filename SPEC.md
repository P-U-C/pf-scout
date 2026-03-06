# pf-scout — Product Specification v2

> **Status**: RFC v2 — revised after first review pass  
> **Author**: zoz (@zozDOTeth) / b1e55ed  
> **Repo**: https://github.com/P-U-C/pf-scout  
> **Review history**: [v1 review comment](https://github.com/P-U-C/pf-scout/pull/1#issuecomment-4012931793)

---

## Changelog from v1

| Section | Change | Reason |
|---------|--------|--------|
| §3.1 Schema | `contacts.handle` → `contacts.id` (UUID) + `identifiers` table | Identity model was the primary flaw in v1 |
| §3.3 Scoring | Auto-scoring demoted to advisory; manual/assisted only for v1 | Determinism claim was too strong without fully specified logic |
| §3.1 Signals | `event_fingerprint` + `source_event_id` replacing payload-hash dedup | Append-only semantics needed explicit event identity |
| §9 Privacy | Safe path is now the default; field classification by tier | Privacy/sharing model was in tension |
| §3.1 Schema | Removed `current_score`/`current_tier` cache fields | Cached truth on `contacts` conflicts with snapshots as source of truth |
| §3.1 Schema | All timestamps explicitly UTC ISO8601 | Enforcement, not just convention |
| §10 SQLite ops | Added PRAGMA requirements, WAL mode, index definitions | Operational requirements were missing |

---

## 1. Problem

Post Fiat has a growing contributor base spread across GitHub, Discord, on-chain task history, and Twitter/X. There is no persistent, queryable record of who these contributors are, what their skills look like, or how their engagement evolves over time.

When b1e55ed reaches its meta-producer gate, the recruitment process will depend on having a maintained, pre-scored pipeline — not a one-time snapshot. Contributors change. A person who was speculative six months ago may have shipped five infrastructure projects since. A highly-scored prospect may have gone quiet.

There is also a broader need: any Post Fiat node operator building a specialist product faces the same recruitment problem against the same contributor base with different fit criteria.

**pf-scout** is a contact intelligence database that solves this for b1e55ed first, then for the PF network broadly.

---

## 2. Core Concept

pf-scout maintains a **persistent, growing profile** for each contact. Every signal collection run appends new data rather than overwriting. Scores are snapshotted at each run so drift is visible over time.

Mental model: a CRM crossed with a signal log.

- **Contact** — canonical identity record (UUID, display label, metadata). Has one or more observed identifiers.
- **Identifier** — an observed platform-specific ID (GitHub handle, wallet address, Twitter handle). Many-to-one with contact.
- **Signal** — a discrete, timestamped piece of evidence collected from one identifier (a commit, a task completion, a Discord message)
- **Snapshot** — a point-in-time scoring of a contact against a rubric
- **Note** — free-text annotation, manual or system-generated

Contacts are **never deleted**. Old signals are never overwritten. The picture only grows.

---

## 3. Architecture

### 3.1 Storage

SQLite. Single file, portable, no server dependency. Default path: `~/.pf-scout/contacts.db`. Overridable via `--db` flag or `PF_SCOUT_DB` env var.

**Operational requirements** (§10 has full detail):
- `PRAGMA foreign_keys = ON` enforced on every connection
- WAL mode enabled on init
- DB file is gitignored by default on `pf-scout init`

```sql
-- ─────────────────────────────────────────────────
-- CONTACTS: canonical identity, one row per person
-- ─────────────────────────────────────────────────
CREATE TABLE contacts (
    id              TEXT PRIMARY KEY,          -- UUID v4, system-assigned
    canonical_label TEXT NOT NULL,             -- best available display name (updated as signals arrive)
    first_seen      TEXT NOT NULL,             -- UTC ISO8601, always suffixed with Z (e.g. 2026-03-06T16:00:00Z)
    last_updated    TEXT NOT NULL,             -- UTC ISO8601, always suffixed with Z (e.g. 2026-03-06T16:00:00Z)
    tags            TEXT NOT NULL DEFAULT '[]',-- JSON array of free-form tags
    notes_count     INTEGER NOT NULL DEFAULT 0,-- denormalized count for display
    archived        INTEGER NOT NULL DEFAULT 0 -- 0=active, 1=soft-deleted (data preserved)
);

-- ─────────────────────────────────────────────────
-- IDENTIFIERS: observed platform-specific IDs
-- Many identifiers → one contact
-- ─────────────────────────────────────────────────
CREATE TABLE identifiers (
    id                  TEXT PRIMARY KEY,      -- UUID v4
    contact_id          TEXT NOT NULL REFERENCES contacts(id) ON DELETE RESTRICT,
    platform            TEXT NOT NULL,         -- "github", "postfiat", "twitter", "discord", "wallet"
    identifier_value    TEXT NOT NULL,         -- the actual handle/address/username
    is_primary          INTEGER NOT NULL DEFAULT 0,  -- 1 = primary display identifier for this platform
    first_seen          TEXT NOT NULL,         -- UTC ISO8601
    last_seen           TEXT NOT NULL,         -- UTC ISO8601
    link_confidence     REAL NOT NULL DEFAULT 1.0,   -- 0.0–1.0: how confident are we this is the same person
    link_source         TEXT,                  -- "manual", "inferred", "self-reported"
    UNIQUE(platform, identifier_value)         -- one person per platform handle
);

-- ─────────────────────────────────────────────────
-- SIGNALS: append-only evidence log
-- One row per discrete observable event
-- ─────────────────────────────────────────────────
CREATE TABLE signals (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id          TEXT NOT NULL REFERENCES contacts(id) ON DELETE RESTRICT,
    identifier_id       TEXT NOT NULL REFERENCES identifiers(id) ON DELETE RESTRICT,  -- which identifier this came from
    collected_at        TEXT NOT NULL,         -- UTC ISO8601: when pf-scout ran the collector
    signal_ts           TEXT,                  -- UTC ISO8601: when the event originally occurred (NULL if unknown)
    source              TEXT NOT NULL,         -- "github", "postfiat", "twitter", "discord", "manual"
    signal_type         TEXT NOT NULL,         -- see Signal Type Registry below
    source_event_id     TEXT,                  -- native provider event ID when available (commit SHA, task ID, etc.)
    event_fingerprint   TEXT NOT NULL,         -- canonical dedup hash; see §4.3
    payload             TEXT NOT NULL,         -- JSON; schema varies by signal_type (see §6)
    evidence_note       TEXT,                  -- human-readable one-liner
    UNIQUE(event_fingerprint)                  -- enforces append-only dedup
);

-- ─────────────────────────────────────────────────
-- SNAPSHOTS: point-in-time scoring
-- One row per (contact, rubric, scoring run)
-- ─────────────────────────────────────────────────
CREATE TABLE snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id          TEXT NOT NULL REFERENCES contacts(id) ON DELETE RESTRICT,
    snapshot_ts         TEXT NOT NULL,         -- UTC ISO8601
    rubric_name         TEXT NOT NULL,
    rubric_version      TEXT NOT NULL,
    trigger             TEXT NOT NULL,         -- "manual", "seed", "scheduled", "update"
    dimension_scores    TEXT NOT NULL,         -- JSON: {dim_id: {score: int, evidence: str, is_manual: bool}}
    total_score         REAL NOT NULL,
    weighted_score      REAL NOT NULL,
    tier                TEXT NOT NULL,
    signals_used        TEXT NOT NULL DEFAULT '[]'  -- JSON array of signal IDs that informed this snapshot
);

-- ─────────────────────────────────────────────────
-- NOTES: free-text annotations
-- ─────────────────────────────────────────────────
CREATE TABLE notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id  TEXT NOT NULL REFERENCES contacts(id) ON DELETE RESTRICT,
    note_ts     TEXT NOT NULL,                 -- UTC ISO8601
    author      TEXT NOT NULL DEFAULT 'system',-- "system" or "manual"
    body        TEXT NOT NULL,
    privacy_tier TEXT NOT NULL DEFAULT 'private' -- "public", "derived", "private"
);

-- ─────────────────────────────────────────────────
-- INDEXES
-- ─────────────────────────────────────────────────
CREATE INDEX idx_identifiers_contact    ON identifiers(contact_id);
-- idx_identifiers_platform is implicit from UNIQUE(platform, identifier_value) — not duplicated
CREATE INDEX idx_signals_contact        ON signals(contact_id);
CREATE INDEX idx_signals_identifier     ON signals(identifier_id);
CREATE INDEX idx_signals_collected      ON signals(collected_at);
CREATE INDEX idx_signals_source         ON signals(source, signal_type);
CREATE INDEX idx_snapshots_contact      ON snapshots(contact_id, rubric_name, snapshot_ts);
CREATE INDEX idx_notes_contact          ON notes(contact_id);
CREATE INDEX idx_signals_fingerprint     ON signals(event_fingerprint); -- explicit name; UNIQUE constraint creates this implicitly
```

**Note**: there are no `current_score` or `current_tier` cache fields on `contacts`. Snapshots are the source of truth. The latest snapshot is always queried when needed — it is cheap in SQLite with the index on `(contact_id, rubric_name, snapshot_ts)`.

### 3.2 Collectors (Pluggable)

Each collector is a Python module implementing a simple interface:

```python
@dataclass
class Signal:
    contact_id: str
    identifier_id: str
    collected_at: str          # UTC ISO8601
    signal_ts: Optional[str]   # UTC ISO8601 or None
    source: str
    signal_type: str
    source_event_id: Optional[str]
    payload: dict              # typed per signal_type
    evidence_note: Optional[str]

class BaseCollector:
    name: str

    def collect(self, identifier: Identifier, db: Database, **kwargs) -> list[Signal]:
        """Return new signals for this identifier. Called on update."""
        ...

    def discover(self, **kwargs) -> list[tuple[str, str]]:
        """Return (platform, identifier_value) pairs to seed. Optional."""
        ...
```

**Bundled collectors:**

| Collector | Signal Types | Auth |
|-----------|-------------|------|
| `github` | `github/commit`, `github/profile`, `github/repo_star` | PAT |
| `postfiat` | `postfiat/capability`, `postfiat/task_completion`, `postfiat/pft_balance` | Session cookie |
| `twitter` | `twitter/profile`, `twitter/post_keyword` | Bearer token |
| `discord` | `discord/message`, `discord/channel_active` | Export file |
| `manual` | `manual/profile`, `manual/score_override`, `manual/note` | None |

Auth credentials are **never stored in the database**. They are passed at runtime via env vars, flags, or OS keychain (see §9).

### 3.3 Scoring Engine — v1: Manual/Assisted Only

**v1 explicitly does not implement auto-scoring.**

The rubric YAML defines dimension descriptions, score guides (1–5 per dimension), and `auto_score_hints` as *advisory metadata* only — documentation for human scorers, not executable logic.

**v1 scoring flow:**

1. `pf-scout update <handle> --rubric rubrics/b1e55ed.yaml` collects new signals and presents a summary
2. For each dimension, the scorer displays recent signals + the score guide and prompts for a score (1–5)
3. Optional: pass `--batch` to skip prompting and create a snapshot with all dimensions marked `needs_review`
4. A `manual_score_override` signal type records the human score with an evidence note and timestamp
5. Manual scores take precedence over any auto-scoring if/when auto-scoring is added in v2

**Why this is the right v1 choice:**
- Preserves the determinism claim: given the same `manual_score_override` signals, scores are fully deterministic
- Avoids encoding hidden evaluator discretion in "scoring hints"
- Human judgment is more accurate than keyword matching for the first 25 contacts
- Auto-scoring can be layered on in v2 once signal patterns are well-understood

**Precedence rules (for v2 planning):**
1. `manual_score_override` signal always wins (most recent if multiple)
2. When auto-scoring lands in v2, it fills dimensions where no manual override exists
3. Auto-scored dimensions are flagged `is_manual: false` in the snapshot

---

## 4. Data Model — Key Design Decisions

### 4.1 Contact/Identifier Separation

`contacts` holds canonical identity. `identifiers` holds observed platform-specific handles. This is not premature abstraction — it is the minimum structure that avoids a painful migration once a contact appears across two platforms.

**Identity linking v1:** manual only. When a human knows that GitHub handle X and wallet Y are the same person:
```bash
pf-scout link github:allenday wallet:rXXX... --confidence 0.95 --source manual
```
This updates both identifiers to point to the same `contact_id` and merges their signal history.

**Identity linking v2:** inferred from overlapping signals (same email in PF profile and GitHub, same profile text, etc.) with `link_confidence < 1.0` and a review queue.

### 4.2 Snapshot-Based Scoring

Scores are never stored on the contact record. Every scoring run creates a new snapshot. This means:
- Score drift is visible without extra work
- Rubric changes don't silently corrupt historical scores (snapshots retain `rubric_version`)
- A contact can be scored against multiple rubrics simultaneously

**Multi-rubric display:** The contact card shows all rubric scores explicitly, each with its rubric name and version. There is no "best tier" rollup — that framing is misleading. Operators choose which rubric is primary for their use case.

### 4.3 Append-Only Event Identity

Every signal has two identity fields:

**`source_event_id`** — the native provider ID, when available:
- GitHub commit: SHA
- PF task: task ID from platform
- Twitter post: tweet ID
- Discord message: message ID
- `NULL` for derived signals (profile snapshots, PFT balance reads)

**`event_fingerprint`** — the storage-level dedup hash. Canonical construction:
```python
import hashlib, json

def event_fingerprint(signal: Signal) -> str:
    canonical = {
        "contact_id": signal.contact_id,
        "source": signal.source,
        "signal_type": signal.signal_type,
        "source_event_id": signal.source_event_id,  # None if not available
        "payload_hash": hashlib.sha256(
            json.dumps(signal.payload, sort_keys=True, ensure_ascii=True).encode()
        ).hexdigest()
    }
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()
```

**Dedup behavior:**
- If `source_event_id` is present → prefer that as the identity basis; payload changes create new signals with note `"updated from source"`
- If `source_event_id` is absent → `event_fingerprint` is the sole dedup key; identical payloads are silently idempotent
- Collectors must declare their idempotency contract: `idempotent=True` means re-running returns the same signals; `idempotent=False` means every run may produce new rows (e.g., message counts at a point in time)

### 4.4 Pseudonymity First

`contacts` has no `name` field. `canonical_label` is the best available human-readable string and may be a pseudonym, a wallet address, or an AI-generated moniker. It is never treated as a real identity assertion.

Real identity information belongs in `notes` with `privacy_tier='private'` and is excluded from all export modes except `--include-private`.

---

## 5. Privacy Model

### 5.1 Field Classification

Every data element is classified into one of four tiers:

| Tier | Examples | Default export behavior |
|------|---------|------------------------|
| **public** | GitHub handle, commit count, PF task count | Always included |
| **derived** | Computed scores, tiers, weighted totals | Included unless `--scores-only` |
| **private** | Manual notes, assumed real names, inferred identity links | Excluded unless `--include-private` |
| **secrets** | Session cookies, API tokens | Never stored, never exported |

### 5.2 Safe-by-Default Sharing

```bash
pf-scout init
```
Creates `~/.pf-scout/` with a `.gitignore` entry covering `contacts.db` and any credential files. The database is never committed unless the operator explicitly removes the gitignore entry.

**Collaboration paths (explicit operator action required):**

```bash
# Export public + derived fields only
pf-scout export --output team-prospects.json

# Export with private notes (operator explicitly opts in)
pf-scout export --include-private --output team-prospects.json

# Anonymized export (no handles, no labels — scores and signals only)
pf-scout export --anonymize --output anonymous-prospects.json
```

**Anonymized export** replaces `canonical_label`, `identifier_value`, and all notes with `[REDACTED]` or pseudorandom tokens. Signal payloads have their user-identifying fields stripped per a per-signal-type redaction map defined in the collector.

### 5.3 Auth Credential Handling

Session cookies and API tokens are **never stored** in the database or any pf-scout config file. They are:
1. Passed at runtime: `pf-scout update --all --cookie "$PF_SESSION_COOKIE"`
2. Or read from env: `PF_SESSION_COOKIE`, `GITHUB_TOKEN`, `TWITTER_BEARER_TOKEN`
3. Or (v2) read from OS keychain via `keyring` library

Token expiry is a known operational pain. v1 documents this explicitly; v2 will add `pf-scout auth check` to validate credentials before a collection run.

---

## 6. Signal Type Registry

Each `signal_type` has a defined payload schema. Collectors must conform.

| signal_type | source | source_event_id | payload fields |
|-------------|--------|-----------------|----------------|
| `github/commit` | github | commit SHA | `repo`, `message_snippet`, `additions`, `deletions`, `ts` |
| `github/profile` | github | NULL | `bio`, `company`, `location`, `public_repos`, `followers` |
| `github/repo_star` | github | `{user}:{repo}` | `repo`, `stars`, `language`, `description_snippet` |
| `postfiat/capability` | postfiat | NULL | `capabilities: []`, `expert_knowledge: []`, `linked_tickers: []` |
| `postfiat/task_completion` | postfiat | task ID | `task_id`, `reward_pft`, `category`, `ts` |
| `postfiat/pft_balance` | postfiat | NULL | `balance`, `snapshot_ts` |
| `twitter/profile` | twitter | NULL | `followers`, `following`, `bio_snippet`, `verified` |
| `twitter/post_keyword` | twitter | tweet ID | `keywords_matched: []`, `engagement_score`, `ts` |
| `discord/message` | discord | message ID | `channel`, `word_count`, `ts` |
| `discord/channel_active` | discord | NULL | `channels: []`, `message_count`, `period_days` |
| `manual/score_override` | manual | NULL | `dimension_id`, `score`, `rationale`, `rubric_name` |
| `manual/note` | manual | NULL | `body`, `privacy_tier` |
| `manual/profile` | manual | NULL | any fields — free-form enrichment |

---

## 7. CLI

```bash
# Initialize workspace
pf-scout init [--db PATH]

# Identity management
pf-scout add <label> --identifier github:<handle> [--identifier wallet:<addr>]
pf-scout link <identifier-a> <identifier-b> --confidence 0.95 --source manual
pf-scout merge <contact-id-a> <contact-id-b>   # merge two contacts

# Bootstrap from a source
pf-scout seed github --org postfiatorg --token $GITHUB_TOKEN
pf-scout seed postfiat --cookie "$PF_SESSION" --base-url https://tasknode.postfiat.org
pf-scout seed csv --file prospects.csv

# Collect signals and score
pf-scout update <identifier>                        # re-collect + prompt for scores
pf-scout update --all --since 7d                    # only if last update >7d ago
pf-scout update <identifier> --batch                # collect without prompting; marks dims as needs_review
pf-scout score <identifier> --rubric rubrics/b1e55ed.yaml  # score without collecting

# Read
pf-scout show <identifier>                          # contact card
pf-scout show <identifier> --history                # include all snapshots
pf-scout show <identifier> --signals                # include raw signal log
pf-scout diff <identifier>                          # latest vs previous snapshot
pf-scout diff <identifier> --since 2026-01-01       # latest vs first snapshot after date
pf-scout list [--tier top] [--rubric rubrics/b1e55ed.yaml]

# Annotate
pf-scout note <identifier> "text"                   # add private note
pf-scout tag <identifier> <tag>                     # add tag
pf-scout archive <identifier>                       # soft-delete

# Output
pf-scout report --rubric rubrics/b1e55ed.yaml --output report.md
pf-scout report --rubric rubrics/b1e55ed.yaml --format csv --output prospects.csv
pf-scout report --rubric rubrics/b1e55ed.yaml --tier top

# Export / backup
pf-scout export --output backup.json
pf-scout export --include-private --output full-backup.json
pf-scout export --anonymize --output share.json
pf-scout export <identifier>                        # single contact
```

---

## 8. Contact Card Format

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Allen Day                             [contact: f3a2-...]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Identifiers:
    github:allenday     (primary, confidence: 1.0, manual)
    [link more: pf-scout link github:allenday wallet:r...]

  First seen:  2026-03-06T16:00:00Z
  Last update: 2026-03-06T16:00:00Z
  Tags:        blockchain-analytics, on-chain-data, infra

  ── SCORES ───────────────────────────────────────────────
  Rubric: b1e55ed.yaml v1.0  |  Snapshot: 2026-03-06  |  🔴 TOP

  ┌─────────────────────────┬───────┬─────────┬──────────────────────────────────┐
  │ Dimension               │ Score │ Method  │ Evidence                         │
  ├─────────────────────────┼───────┼─────────┼──────────────────────────────────┤
  │ Quantitative Depth      │  5/5  │ manual  │ PhD human genetics; BigQuery ML  │
  │ Infrastructure Cap.     │  4/5  │ manual  │ Google Cloud; 24 PF GH commits   │
  │ Market Analysis         │  2/5  │ manual  │ No market-facing output observed │
  │ Signal Generation       │  5/5  │ manual  │ Public BTC/ETH/XRP BigQuery sets │
  │ Engagement Consistency  │  3/5  │ manual  │ GitHub active; PF tasks: 0       │
  └─────────────────────────┴───────┴─────────┴──────────────────────────────────┘
  Weighted: 24.9  |  Raw: 19/25

  ── SCORE HISTORY ────────────────────────────────────────
  2026-03-06  24.9  🔴 TOP   b1e55ed.yaml v1.0  (seed)

  ── SIGNALS (5 most recent) ──────────────────────────────
  2026-03-06  github/profile   bio: "PhD. Google Cloud BigQuery..." [public]
  2026-03-06  github/commit    postfiatorg/.github.io ×24 commits   [public]

  ── NOTES ────────────────────────────────────────────────
  2026-03-06 [system]  Seeded from postfiatorg GitHub org scan
  [private notes hidden — use --include-private to show]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 9. Rubric Format (YAML)

```yaml
name: b1e55ed Producer Fit
version: "1.0"

dimensions:
  - id: quant_depth
    name: Quantitative Depth
    weight: 1.5
    description: Statistical, ML, or quantitative finance background
    # auto_score_hints: advisory only in v1 — for human scorers, not executable logic
    auto_score_hints:
      relevant_signals: ["github/profile", "postfiat/capability"]
      keywords: ["quant", "ml", "phd", "statistics", "data science", "algo"]
      note: "Keywords in bio/company/capabilities suggest this dimension. Human scorer decides."
    score_guide:
      5: "PhD/professional quant, published models, production ML systems"
      4: "Strong ML/stats background, applied quantitative work on GitHub"
      3: "Engineering-first with quantitative exposure (data pipelines, analytics)"
      2: "Some data skills, limited quant focus"
      1: "No observable quantitative background"

  - id: infra_capability
    name: Infrastructure Capability
    weight: 1.2
    description: Can build and operate server-side data pipelines and nodes
    auto_score_hints:
      relevant_signals: ["github/commit"]
      commit_count_guidance: "10+ commits → start at 2; 50+ → 3; 100+ → 4; 500+ → 5 (adjust for quality)"
      note: "High commit counts in infra repos (rippled fork, validator-history) are strong signals."
    score_guide:
      5: "Production infra, validators, distributed systems at scale"
      4: "Active DevOps/backend contributor, cloud infra history"
      3: "Can self-host services, moderate infra experience"
      2: "Limited infra exposure"
      1: "No observable infrastructure capability"

  - id: market_analysis
    name: Market Analysis / Forecasting
    weight: 1.3
    description: Track record of structured market commentary or quantitative market analysis
    auto_score_hints:
      relevant_signals: ["twitter/profile", "twitter/post_keyword", "postfiat/task_completion"]
      keywords: ["trader", "portfolio manager", "macro", "alpha", "market analyst", "pm"]
    score_guide:
      5: "Professional trader/PM, published systematic research, verifiable public calls"
      4: "Regular structured market analysis with verifiable outputs"
      3: "Market-aware, occasional structured analysis"
      2: "Crypto-native, limited analytical depth"
      1: "No market analysis observable"

  - id: signal_generation
    name: Signal Generation History
    weight: 1.4
    description: Has produced data-driven signals from on-chain, market, or social data
    auto_score_hints:
      relevant_signals: ["github/profile", "postfiat/capability", "github/repo_star"]
      keywords: ["signal", "analytics", "bigquery", "pipeline", "etl", "on-chain", "blockchain analytics"]
    score_guide:
      5: "Built production signal pipelines, published systematic alpha research"
      4: "ETL/analytics for market or on-chain data; blockchain analytics background"
      3: "Data engineering applicable to signal production (APIs, scrapers, pipelines)"
      2: "Some data work, not signal-focused"
      1: "No signal generation background observable"

  - id: engagement_consistency
    name: Engagement Consistency
    weight: 1.0
    description: Reliable, sustained engagement with the Post Fiat ecosystem
    auto_score_hints:
      relevant_signals: ["github/commit", "postfiat/task_completion", "discord/message"]
      pf_task_guidance: "5+ tasks → 2; 20+ → 3; 50+ → 4; 100+ → 5 (adjust for recency)"
    score_guide:
      5: "Core contributor, consistent multi-month, daily/weekly presence"
      4: "Regular, multiple months verifiable, responds and ships"
      3: "Periodic, engaged when active but inconsistent"
      2: "One-time or sparse contribution"
      1: "Minimal or no verifiable engagement"

tiers:
  top:         { label: "🔴 TOP",         min_pct: 0.64 }
  mid:         { label: "🟡 MID",         min_pct: 0.40 }
  speculative: { label: "⚪ SPECULATIVE",  min_pct: 0.0  }
```

---

## 10. SQLite Operational Requirements

Applied on every connection:

```python
def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")  # safe with WAL
    conn.row_factory = sqlite3.Row
    return conn
```

**Backup:** `pf-scout export --output backup.json` is the primary backup mechanism. The SQLite file can also be copied directly when no write is in progress (WAL mode makes this safe). No automated backup in v1; document this explicitly.

**Migration:** Schema migrations use `PRAGMA user_version` (a single integer in SQLite's file header, readable without parsing any table, survives partial schema corruption). `PRAGMA user_version = N` after applying migration N. On open, check version; if behind, apply migrations in order. Never alter tables destructively.

---

## 11. Out of Scope (v1)

- Auto-scoring (v2) — advisory hints only in v1
- Inferred identity linking (v2) — manual linking only in v1
- Web UI — CLI only
- Real-time streaming — batch collection only
- Automatic outreach integration — pipeline doc only, not a dialer
- Hosted/multi-user mode — local-first; share via `pf-scout export`
- On-chain storage of scores — privacy concern; local only

---

## 12. Open Questions (Remaining After v1 Revision)

These were addressed or deferred; documenting resolution:

| Question | Resolution |
|----------|-----------|
| Typed signals vs free-form JSON | **Typed per signal_type** (§6 registry). Free-form `payload` within each type. |
| Dedup strategy | **`event_fingerprint` + `source_event_id`** (§4.3). Fully specified. |
| Rubric versioning | **Snapshots store `rubric_version`**. Old snapshots are incompatible with new rubric versions and flagged as such in `pf-scout diff`. |
| Score decay | **Deferred to v2.** `engagement_consistency` score guide explicitly says "adjust for recency" as a human scorer instruction. Algorithmic decay requires more signal history to calibrate. |
| Multi-handle contacts | **Contact/identifier model** (§3.1, §4.1). Explicit `link_confidence` field. Manual linking in v1, inferred in v2. |
| Auth management | **Never stored**. Runtime env vars in v1; OS keychain via `keyring` in v2. |

---

## 13. Implementation Plan

| Phase | Scope | Status |
|-------|-------|--------|
| v0 | One-shot CSV → score → markdown prototype | ✅ Done (workspace) |
| v1 | SQLite store + contact/identifier model + seed/update/show/report CLI + GitHub + manual collectors + manual scoring | 🔲 This spec |
| v2 | PF platform collector, auto-scoring engine, inferred identity linking, score decay, OS keychain auth | 🔲 Roadmap |
| v3 | Twitter collector, Discord export collector, multi-rubric reports, alert system | 🔲 Roadmap |
| v4 | Web UI, hosted mode, team sharing | 🔲 Roadmap |
