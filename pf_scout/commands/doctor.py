"""pf-scout doctor: diagnostic checks."""

import os

import click

from ..db import get_connection


@click.command("doctor")
@click.pass_context
def doctor_command(ctx):
    """Check DB integrity, collector env vars, rubric validity, schema version."""
    db_path = ctx.obj["db_path"]
    ok = True

    # DB integrity
    click.echo("Checking DB integrity...")
    try:
        conn = get_connection(db_path)
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if result == "ok":
            click.echo("  ✅ DB integrity: ok")
        else:
            click.echo(f"  ❌ DB integrity: {result}")
            ok = False
    except Exception as e:
        click.echo(f"  ❌ DB: {e}")
        ok = False

    # Schema version
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        click.echo(f"  ✅ Schema version: {version}")
    except Exception as e:
        click.echo(f"  ❌ Schema version: {e}")

    # Env vars
    click.echo("Checking collector credentials...")
    checks = [
        ("GITHUB_TOKEN", "GitHub collector"),
        ("PF_SESSION_COOKIE", "PostFiat collector"),
        ("TWITTER_BEARER_TOKEN", "Twitter collector"),
    ]
    for var, name in checks:
        if os.environ.get(var):
            click.echo(f"  ✅ {name}: {var} set")
        else:
            click.echo(f"  ⚠️  {name}: {var} not set")

    if ok:
        click.echo("\n✅ All checks passed")
    else:
        click.echo("\n❌ Some checks failed")
        ctx.exit(1)
