"""pf-scout set-context — fetch your own PF Context document."""
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

import click
import requests

from ..collectors.postfiat import _parse_context_sections


def _now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@click.command("set-context")
@click.option("--cookie", envvar="PF_SESSION_COOKIE", help="Tasknode session cookie")
@click.option("--file", "file_path", type=click.Path(exists=True), help="Load from local file instead")
@click.option("--base-url", default="https://tasknode.postfiat.org", help="Tasknode base URL")
@click.pass_context
def set_context_cmd(ctx, cookie, file_path, base_url):
    """Fetch your PF Context document and use it as the recruiter scoring lens."""
    db_path = ctx.obj["db_path"]
    scout_dir = Path(db_path).parent
    context_path = scout_dir / "my-context.md"
    state_path = scout_dir / "context-state.json"

    if file_path:
        raw_markdown = Path(file_path).read_text()
        source = "file"
    elif cookie:
        try:
            resp = requests.get(
                f"{base_url}/context",
                headers={"Cookie": cookie, "User-Agent": "pf-scout/0.1.0"},
                timeout=10,
            )
            if resp.status_code != 200:
                click.echo(f"❌ Failed to fetch context: HTTP {resp.status_code}")
                ctx.exit(1)
                return
            raw_markdown = resp.text
            source = "tasknode"
        except requests.RequestException as e:
            click.echo(f"❌ Network error: {e}")
            ctx.exit(1)
            return
    else:
        click.echo("❌ Provide --cookie or --file")
        ctx.exit(1)
        return

    content_hash = hashlib.sha256(raw_markdown.encode()).hexdigest()
    sections = _parse_context_sections(raw_markdown)
    word_count = len(raw_markdown.split())

    # Ensure directory exists
    scout_dir.mkdir(parents=True, exist_ok=True)

    # Write context file
    context_path.write_text(raw_markdown)

    # Write state
    state = {
        "fetched_at": _now_utc(),
        "content_hash": f"sha256:{content_hash}",
        "source": source,
        "version_label": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "word_count": word_count,
    }
    state_path.write_text(json.dumps(state, indent=2))

    # Ensure my-context.md and context-state.json are gitignored
    gitignore_path = scout_dir / ".gitignore"
    entries_to_add = ["my-context.md", "context-state.json"]
    existing = gitignore_path.read_text() if gitignore_path.exists() else ""
    with open(gitignore_path, "a") as f:
        for entry in entries_to_add:
            if entry not in existing:
                f.write(f"{entry}\n")

    click.echo(f"✅ Context updated ({word_count} words, {state['version_label']})")
    click.echo(f"   Stored at: {context_path}")

    if sections.get("value"):
        click.echo(f"\n  Value:    {sections['value'][:80]}...")
    if sections.get("strategy"):
        click.echo(f"  Strategy: {sections['strategy'][:80]}...")
    if sections.get("tactics"):
        first_tactic = sections["tactics"].split("\n")[0]
        click.echo(f"  Tactics:  {first_tactic[:80]}")
