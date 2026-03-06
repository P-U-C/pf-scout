"""Basic tests for pf-scout."""

import json
import os
import uuid
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from pf_scout.cli import cli
from pf_scout.schema import init_db
from pf_scout.db import get_connection


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary database."""
    db_path = str(tmp_path / "test.db")
    return db_path


@pytest.fixture
def initialized_db(tmp_db):
    """Create and initialize a temporary database."""
    conn = init_db(tmp_db)
    conn.close()
    return tmp_db


@pytest.fixture
def runner():
    return CliRunner()


class TestInit:
    """Phase 1: init command tests."""

    def test_init_creates_db_with_correct_schema(self, tmp_db):
        conn = init_db(tmp_db)
        # Check user_version
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == 1

        # Check all tables exist
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()]
        assert "contacts" in tables
        assert "identifiers" in tables
        assert "signals" in tables
        assert "snapshots" in tables
        assert "notes" in tables
        conn.close()

    def test_init_is_idempotent(self, tmp_db):
        """Running init twice shouldn't error."""
        conn1 = init_db(tmp_db)
        conn1.close()
        conn2 = init_db(tmp_db)
        version = conn2.execute("PRAGMA user_version").fetchone()[0]
        assert version == 1
        conn2.close()

    def test_init_command(self, runner, tmp_path):
        db_path = str(tmp_path / "cmd_test.db")
        result = runner.invoke(cli, ["--db", db_path, "init"])
        assert result.exit_code == 0
        assert "Initialized" in result.output
        assert os.path.exists(db_path)

    def test_init_creates_gitignore(self, runner, tmp_path):
        db_path = str(tmp_path / "sub" / "contacts.db")
        result = runner.invoke(cli, ["--db", db_path, "init"])
        assert result.exit_code == 0
        gitignore = tmp_path / "sub" / ".gitignore"
        assert gitignore.exists()
        assert "contacts.db" in gitignore.read_text()


class TestAdd:
    """Phase 2: add command tests."""

    def test_add_creates_contact_and_identifier(self, runner, initialized_db):
        result = runner.invoke(cli, [
            "--db", initialized_db,
            "add", "allenday",
            "--identifier", "github:allenday"
        ])
        assert result.exit_code == 0
        assert "allenday" in result.output

        conn = get_connection(initialized_db)
        contacts = conn.execute("SELECT * FROM contacts").fetchall()
        assert len(contacts) == 1
        assert contacts[0]["canonical_label"] == "allenday"

        identifiers = conn.execute("SELECT * FROM identifiers").fetchall()
        assert len(identifiers) == 1
        assert identifiers[0]["platform"] == "github"
        assert identifiers[0]["identifier_value"] == "allenday"
        conn.close()

    def test_add_multiple_identifiers(self, runner, initialized_db):
        result = runner.invoke(cli, [
            "--db", initialized_db,
            "add", "testuser",
            "--identifier", "github:testuser",
            "--identifier", "wallet:0xabc123"
        ])
        assert result.exit_code == 0

        conn = get_connection(initialized_db)
        identifiers = conn.execute("SELECT * FROM identifiers").fetchall()
        assert len(identifiers) == 2
        conn.close()


class TestShow:
    """Phase 2: show command tests."""

    def test_show_renders_contact_card(self, runner, initialized_db):
        # First add a contact
        runner.invoke(cli, [
            "--db", initialized_db,
            "add", "allenday",
            "--identifier", "github:allenday"
        ])
        # Then show it
        result = runner.invoke(cli, [
            "--db", initialized_db,
            "show", "github:allenday"
        ])
        assert result.exit_code == 0
        assert "allenday" in result.output

    def test_show_json_format(self, runner, initialized_db):
        runner.invoke(cli, [
            "--db", initialized_db,
            "add", "allenday",
            "--identifier", "github:allenday"
        ])
        result = runner.invoke(cli, [
            "--db", initialized_db,
            "show", "github:allenday",
            "--format", "json"
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["canonical_label"] == "allenday"


class TestSeed:
    """Phase 3: seed command tests."""

    def test_seed_github_creates_contacts(self, runner, initialized_db):
        """Test seed command with mocked GitHub API."""
        with patch('pf_scout.collectors.github.time.sleep'):
            with patch('pf_scout.collectors.github.requests.get') as mock_get:
                # Track calls to handle pagination
                call_count = {"repos": 0}

                # Setup mock responses
                def mock_response(url, **kwargs):
                    resp = MagicMock()
                    resp.headers = {}

                    if "/orgs/" in url and "/repos" in url:
                        call_count["repos"] += 1
                        resp.status_code = 200
                        # Return repos on first call, empty on second (pagination end)
                        if call_count["repos"] == 1:
                            resp.json.return_value = [{"name": "repo1", "fork": False}]
                        else:
                            resp.json.return_value = []
                    elif "/contributors" in url:
                        resp.status_code = 200
                        resp.json.return_value = [
                            {"login": "user1", "type": "User", "contributions": 10}
                        ]
                    elif "/users/user1/repos" in url:
                        resp.status_code = 200
                        resp.json.return_value = []
                    elif "/users/user1" in url:
                        resp.status_code = 200
                        resp.json.return_value = {
                            "login": "user1", "bio": "Dev", "company": None,
                            "location": None, "public_repos": 5, "followers": 10,
                            "created_at": "2020-01-01T00:00:00Z"
                        }
                    else:
                        resp.status_code = 404
                        resp.json.return_value = {}
                    return resp

                mock_get.side_effect = mock_response

                result = runner.invoke(cli, [
                    "--db", initialized_db,
                    "seed", "github",
                    "--org", "test-org",
                    "--token", "fake-token"
                ])

                assert result.exit_code == 0
                assert "Seeded" in result.output

                conn = get_connection(initialized_db)
                contacts = conn.execute("SELECT * FROM contacts").fetchall()
                assert len(contacts) >= 1
                conn.close()

    def test_seed_skips_bots(self, runner, initialized_db):
        """Test that bots are skipped during seed."""
        with patch('pf_scout.collectors.github.time.sleep'):
            with patch('pf_scout.collectors.github.requests.get') as mock_get:
                call_count = {"repos": 0}

                def mock_response(url, **kwargs):
                    resp = MagicMock()
                    resp.headers = {}

                    if "/orgs/" in url and "/repos" in url:
                        call_count["repos"] += 1
                        resp.status_code = 200
                        if call_count["repos"] == 1:
                            resp.json.return_value = [{"name": "repo1", "fork": False}]
                        else:
                            resp.json.return_value = []
                    elif "/contributors" in url:
                        resp.status_code = 200
                        resp.json.return_value = [
                            {"login": "dependabot[bot]", "type": "Bot", "contributions": 50}
                        ]
                    else:
                        resp.status_code = 404
                        resp.json.return_value = {}
                    return resp

                mock_get.side_effect = mock_response

                result = runner.invoke(cli, [
                    "--db", initialized_db,
                    "seed", "github",
                    "--org", "test-org",
                    "--token", "fake-token"
                ])

                assert result.exit_code == 0

                conn = get_connection(initialized_db)
                contacts = conn.execute("SELECT * FROM contacts").fetchall()
                assert len(contacts) == 0
                conn.close()


class TestPostFiatContext:
    """PF Context integration tests."""

    def test_postfiat_context_signal_dedup(self, initialized_db):
        """Same context hash → INSERT OR IGNORE, no duplicate signal."""
        conn = get_connection(initialized_db)
        now = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
        contact_id = str(uuid.uuid4())
        ident_id = str(uuid.uuid4())

        conn.execute(
            "INSERT INTO contacts (id, canonical_label, first_seen, last_updated) VALUES (?, ?, ?, ?)",
            (contact_id, "pf_test", now, now)
        )
        conn.execute(
            "INSERT INTO identifiers (id, contact_id, platform, identifier_value, first_seen, last_seen) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ident_id, contact_id, "wallet", "rXRPwallet123", now, now)
        )
        conn.commit()

        import hashlib
        raw_md = "## Value\nBlockchain analytics\n## Strategy\nBuild infra"
        content_hash = hashlib.sha256(raw_md.encode()).hexdigest()
        payload = json.dumps({"raw_markdown": raw_md, "word_count": 5})

        from pf_scout.fingerprint import compute_event_fingerprint

        fp = compute_event_fingerprint(contact_id, "postfiat", "postfiat/context", content_hash, json.loads(payload))

        # First insert
        conn.execute(
            "INSERT OR IGNORE INTO signals "
            "(contact_id, identifier_id, collected_at, source, signal_type, source_event_id, event_fingerprint, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (contact_id, ident_id, now, "postfiat", "postfiat/context", content_hash, fp, payload)
        )
        conn.commit()

        # Duplicate insert — same fingerprint, should be silently ignored
        conn.execute(
            "INSERT OR IGNORE INTO signals "
            "(contact_id, identifier_id, collected_at, source, signal_type, source_event_id, event_fingerprint, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (contact_id, ident_id, now, "postfiat", "postfiat/context", content_hash, fp, payload)
        )
        conn.commit()

        count = conn.execute(
            "SELECT COUNT(*) FROM signals WHERE signal_type = 'postfiat/context'"
        ).fetchone()[0]
        assert count == 1
        conn.close()

    def test_rerank_no_context(self, runner, initialized_db):
        """rerank runs without error when my-context.md doesn't exist."""
        # Add 2 contacts
        runner.invoke(cli, [
            "--db", initialized_db,
            "add", "user1",
            "--identifier", "github:user1"
        ])
        runner.invoke(cli, [
            "--db", initialized_db,
            "add", "user2",
            "--identifier", "github:user2"
        ])

        result = runner.invoke(cli, [
            "--db", initialized_db,
            "rerank"
        ])
        assert result.exit_code == 0
        assert "RERANK" in result.output
        assert "2 contacts" in result.output

    def test_set_context_from_file(self, runner, tmp_path):
        """set-context --file writes my-context.md and context-state.json."""
        # Setup DB in tmp_path so context files land there
        db_path = str(tmp_path / "contacts.db")
        runner.invoke(cli, ["--db", db_path, "init"])

        md = "## Value\nBlockchain analytics\n## Strategy\nBuild infra\n## Tactics\n1. Launch product"
        f = tmp_path / "ctx.md"
        f.write_text(md)

        result = runner.invoke(cli, [
            "--db", db_path,
            "set-context",
            "--file", str(f)
        ])
        assert result.exit_code == 0
        assert "Context updated" in result.output

        context_path = tmp_path / "my-context.md"
        assert context_path.exists()
        assert context_path.read_text() == md

        state_path = tmp_path / "context-state.json"
        assert state_path.exists()
        state = json.loads(state_path.read_text())
        assert "content_hash" in state
        assert state["content_hash"].startswith("sha256:")
        assert state["source"] == "file"

    def test_parse_context_sections(self):
        """_parse_context_sections extracts Value, Strategy, Tactics."""
        from pf_scout.collectors.postfiat import _parse_context_sections

        md = """## Value
Build on-chain analytics tools

## Strategy
Focus on data pipelines

## Tactics
1. Launch MVP
2. Iterate on feedback
"""
        sections = _parse_context_sections(md)
        assert "value" in sections
        assert "analytics" in sections["value"]
        assert "strategy" in sections
        assert "pipelines" in sections["strategy"]
        assert "tactics" in sections
        assert "MVP" in sections["tactics"]

    def test_alignment_notes(self):
        """_alignment_notes finds keyword overlaps."""
        from pf_scout.commands.rerank import _alignment_notes

        my_keywords = ["blockchain", "analytics", "infrastructure", "python", "data"]
        prospect = "I work on blockchain data analytics and infrastructure projects."
        matches = _alignment_notes(my_keywords, prospect)
        assert len(matches) > 0
        assert "blockchain" in matches
        assert "analytics" in matches


class TestWizard:
    """Wizard command tests."""

    def test_wizard_invokes_without_error(self, tmp_db, runner):
        """Wizard --yes flag runs non-interactively without crashing."""
        result = runner.invoke(cli, ["--db", tmp_db, "wizard", "--yes"])
        assert result.exit_code == 0

    def test_wizard_yes_creates_db(self, tmp_db, runner):
        """Wizard --yes initializes the database."""
        result = runner.invoke(cli, ["--db", tmp_db, "wizard", "--yes"])
        assert result.exit_code == 0
        assert "Setup complete" in result.output
        assert os.path.exists(tmp_db)

    def test_wizard_yes_shows_summary(self, tmp_db, runner):
        """Wizard --yes prints summary with next steps."""
        result = runner.invoke(cli, ["--db", tmp_db, "wizard", "--yes"])
        assert result.exit_code == 0
        assert "Next steps" in result.output
        assert "pf-scout list" in result.output


class TestDuplicateSignal:
    """Test that duplicate signals are silently ignored."""

    def test_duplicate_fingerprint_ignored(self, initialized_db):
        conn = get_connection(initialized_db)
        now = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
        contact_id = str(uuid.uuid4())
        ident_id = str(uuid.uuid4())

        conn.execute(
            "INSERT INTO contacts (id, canonical_label, first_seen, last_updated) VALUES (?, ?, ?, ?)",
            (contact_id, "test", now, now)
        )
        conn.execute(
            "INSERT INTO identifiers (id, contact_id, platform, identifier_value, first_seen, last_seen) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ident_id, contact_id, "github", "testuser", now, now)
        )
        conn.commit()

        fingerprint = "test_fingerprint_123"
        payload = json.dumps({"test": True})

        # First insert
        conn.execute(
            "INSERT OR IGNORE INTO signals "
            "(contact_id, identifier_id, collected_at, source, signal_type, event_fingerprint, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (contact_id, ident_id, now, "test", "test/signal", fingerprint, payload)
        )
        conn.commit()

        # Duplicate insert — should be silently ignored
        conn.execute(
            "INSERT OR IGNORE INTO signals "
            "(contact_id, identifier_id, collected_at, source, signal_type, event_fingerprint, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (contact_id, ident_id, now, "test", "test/signal", fingerprint, payload)
        )
        conn.commit()

        count = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        assert count == 1
        conn.close()
