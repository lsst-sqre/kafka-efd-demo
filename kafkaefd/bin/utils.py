"""Helpers for command-line tools.
"""

__all__ = ('get_broker_url',)

from click import ClickException


def get_broker_url(ctx):
    """Get the broker connection string from the context, or print an error
    message otherwise.
    """
    try:
        broker_url = ctx.obj['broker_url']
    except KeyError:
        message = (
            'Broker is not configured. Pass a --broker option to kafkaefd '
            'or set the $BROKER environment variable. An example connection '
            'string is "localhost:9092".'
        )
        raise ClickException(message)
    return broker_url
