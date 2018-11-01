"""Main command-line interface.
"""

__all__ = ('main',)

import click

# Add -h as a help shortcut option
CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(message='%(version)s')
@click.pass_context
def main(ctx):
    """kafkaefd is a collection of subcommands that implement experimental
    Kafka producers and consumers. kafkaefd is a test bed for the Kafka
    technology that will underly the DM Engineering Facility Database (EFD).
    """
    # Subcommands should use the click.pass_obj decorator to get this
    # ctx.obj object as the first argument. Subcommands shouldn't create their
    # own Repo instance.
    ctx.obj = {}


@main.command()
@click.argument('topic', default=None, required=False, nargs=1)
@click.pass_context
def help(ctx, topic, **kw):
    """Show help for any command.
    """
    # The help command implementation is taken from
    # https://www.burgundywall.com/post/having-click-help-subcommand
    if topic is None:
        click.echo(ctx.parent.get_help())
    else:
        click.echo(main.commands[topic].get_help(ctx))
