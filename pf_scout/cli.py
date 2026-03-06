"""pf-scout CLI entry point."""

import os
import click
from .commands.init import init_command
from .commands.add import add_command
from .commands.link import link_command
from .commands.show import show_command
from .commands.seed import seed_group

DEFAULT_DB = os.path.expanduser("~/.pf-scout/contacts.db")


@click.group()
@click.option("--db", "db_path", default=None, envvar="PF_SCOUT_DB",
              help="Path to database file")
@click.pass_context
def cli(ctx, db_path):
    """pf-scout: Contact intelligence for Post Fiat contributor recruitment."""
    ctx.ensure_object(dict)
    ctx.obj["db_path"] = db_path or DEFAULT_DB


cli.add_command(init_command)
cli.add_command(add_command)
cli.add_command(link_command)
cli.add_command(show_command)
cli.add_command(seed_group)


def main():
    cli()


if __name__ == "__main__":
    main()
