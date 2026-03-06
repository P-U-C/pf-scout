"""pf-scout init command."""

import os
import click
from pathlib import Path
from ..schema import init_db

DEFAULT_DIR = os.path.expanduser("~/.pf-scout")
DEFAULT_DB = os.path.join(DEFAULT_DIR, "contacts.db")


@click.command("init")
@click.pass_context
def init_command(ctx):
    """Initialize the pf-scout database."""
    db_path = ctx.obj.get("db_path") or DEFAULT_DB

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
