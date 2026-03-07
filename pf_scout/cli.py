"""pf-scout CLI entry point."""

import os
import click
from .__version__ import __version__
from .commands.init import init_command
from .commands.add import add_command
from .commands.link import link_command
from .commands.show import show_command
from .commands.seed import seed_group
from .commands.update import update_command
from .commands.doctor import doctor_command
from .commands.set_context import set_context_cmd
from .commands.rerank import rerank_cmd
from .commands.wizard import wizard_cmd
from .commands.prospect import prospect_cmd
from .commands.diff import diff_command
from .commands.merge import merge_cmd
from .commands.tag import tag_cmd
from .commands.archive import archive_cmd
from .commands.list import list_command
from .commands.export import export_command
from .commands.note import note_command

DEFAULT_DB = os.path.expanduser("~/.pf-scout/contacts.db")


@click.group()
@click.version_option(version=__version__, prog_name="pf-scout")
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
cli.add_command(update_command)
cli.add_command(doctor_command)
cli.add_command(set_context_cmd)
cli.add_command(rerank_cmd)
cli.add_command(wizard_cmd)
cli.add_command(prospect_cmd)
cli.add_command(diff_command)
cli.add_command(merge_cmd)
cli.add_command(tag_cmd)
cli.add_command(archive_cmd)
cli.add_command(list_command)
cli.add_command(export_command)
cli.add_command(note_command)


def main():
    cli()


if __name__ == "__main__":
    main()
