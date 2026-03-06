"""Basic tests for pf-scout."""

import json
import os
import sqlite3
import tempfile
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
