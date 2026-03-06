"""pf-scout init command."""

import os
import click
from pathlib import Path
from ..schema import init_db

DEFAULT_DIR = os.path.expanduser("~/.pf-scout")
DEFAULT_DB = os.path.join(DEFAULT_DIR, "contacts.db")


@click.command("init")
@click.option("--db", "db_path", default=None, help="Path to database file")
def init_command(db_path):
    """Initialize the pf-scout database."""
    if db_path is None:
        db_path = DEFAULT_DB

    db_dir = os.path.dirname(db_path)

    # Create directory
    os.makedirs(db_dir, exist_ok=True)

    # Write .gitignore
    gitignore_path = os.path.join(db_dir, ".gitignore")
    with open(gitignore_path, "w") as f:
        f.write("contacts.db\n")

    # Initialize database
    conn = init_db(db_path)
    conn.close()

    click.echo(f"✓ Initialized pf-scout database at {db_path}")
