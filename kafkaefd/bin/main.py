"""Main command-line interface.
"""

__all__ = ('main',)

import click

from .admin import admin
from .registry import registry
from .salschema import salschema
from .salmock import salmock
from .helloworld import helloworld
from .helloavro import helloavro
from .aioload import aioload
from .saltransform import saltransform

# Add -h as a help shortcut option
CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])


@click.group(context_settings=CONTEXT_SETTINGS)
@click.option(
    '--broker', 'broker_url', envvar='BROKER', required=False, nargs=1,
    default='confluent-kafka-cp-kafka-headless:9092',
    show_default=True,
    help='Kafka broker. Alternatively set via $BROKER env var.'
)
@click.option(
    '--registry', 'schema_registry_url', envvar='SCHEMAREGISTRY',
    required=False, nargs=1,
    default='http://confluent-kafka-cp-schema-registry:8081',
    show_default=True,
    help='Schema Registry URL. Alternatively set via $SCHEMAREGISTRY env var.'
)
@click.option(
    '--kafka-connect', 'kafka_connect_url', envvar='KAFKA_CONNECT',
    required=False, nargs=1,
    default='http://confluent-kafka-cp-kafka-connect:8083',
    show_default=True,
    help='Kafka Connect URL. Alternatively set via $KAFKA_CONNECT env var.'
)
@click.version_option(message='%(version)s')
@click.pass_context
def main(ctx, broker_url, schema_registry_url, kafka_connect_url):
    """kafkaefd is a collection of subcommands that implement experimental
    Kafka producers and consumers. kafkaefd is a test bed for the Kafka
    technology that will underly the DM Engineering Facility Database (EFD).
    """
    # Subcommands should use the click.pass_obj decorator to get this
    # ctx object as the first argument.
    ctx.obj = {
        'broker_url': broker_url,
        'schema_registry_url': schema_registry_url,
        'kafka_connect_url': kafka_connect_url,
    }


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


# Add subcommands from other modules
main.add_command(admin)
main.add_command(registry)
main.add_command(salschema)
main.add_command(salmock)
main.add_command(helloworld)
main.add_command(helloavro)
main.add_command(aioload)
main.add_command(saltransform)
