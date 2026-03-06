"""pf-scout doctor: diagnostic checks."""

import os
from pathlib import Path

import click

from ..db import get_connection
from ..rubric import validate_rubric


@click.command("doctor")
@click.option("--rubric", "rubric_path", type=click.Path(exists=True), default=None,
              help="Validate a rubric YAML file")
@click.pass_context
def doctor_command(ctx, rubric_path):
    """Check DB integrity, collector env vars, rubric validity, schema version."""
    db_path = ctx.obj["db_path"]
    ok = True

    # If --rubric is specified, validate that specific rubric
    if rubric_path:
        click.echo(f"Validating rubric: {rubric_path}")
        errors = validate_rubric(rubric_path)
        if errors:
            click.echo("  ❌ Rubric validation failed:")
            for err in errors:
                click.echo(f"     • {err}")
            ok = False
        else:
            click.echo("  ✅ Rubric is valid")
        
        # When validating rubric only, show summary and exit
        if ok:
            click.echo("\n✅ Rubric validation passed")
        else:
            click.echo("\n❌ Rubric validation failed")
            ctx.exit(1)
        return

    # Standard doctor checks
    
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

    # Auto-validate rubrics in ./rubrics/ if they exist
    rubrics_dir = Path("rubrics")
    if rubrics_dir.exists() and rubrics_dir.is_dir():
        click.echo("Checking rubrics...")
        rubric_files = list(rubrics_dir.glob("*.yaml")) + list(rubrics_dir.glob("*.yml"))
        if rubric_files:
            for rf in rubric_files:
                errors = validate_rubric(rf)
                if errors:
                    click.echo(f"  ❌ {rf.name}: {len(errors)} error(s)")
                    for err in errors[:3]:  # Show first 3 errors
                        click.echo(f"     • {err}")
                    ok = False
                else:
                    click.echo(f"  ✅ {rf.name}: valid")
        else:
            click.echo("  ⚠️  No rubric files found in ./rubrics/")

    if ok:
        click.echo("\n✅ All checks passed")
    else:
        click.echo("\n❌ Some checks failed")
        ctx.exit(1)
