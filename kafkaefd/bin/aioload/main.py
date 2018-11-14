"""Implementation of the kafkaefd aioload commands for testing latency
in Kafka production and consumption under different loads (topic volume and
frequency).
"""

__all__ = ('aioload',)

import click


@click.group()
@click.pass_context
def aioload(ctx):
    """Test kafka produce-consume latency under different topic population
    and frequency loads.

    Messages are consumed and produced asynchronously with aiokafka.
    """
    ctx.obj = {}
