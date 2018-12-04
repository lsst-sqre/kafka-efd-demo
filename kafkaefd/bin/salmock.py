"""Mock SAL producers.
"""

__all__ = ('salmock',)

import logging

import click
import structlog


@click.group()
@click.pass_context
def salmock(ctx):
    """Mock SAL producers.
    """
    ctx.obj = {}


@salmock.command()
@click.option(
    '--log-level', 'log_level',
    type=click.Choice(['debug', 'info', 'warning']),
    default='info', help='Logging level'
)
@click.option(
    '--prometheus-port', 'prometheus_port', type=int, default=9092,
    help='Port for the Prometheus metrics scraping endpoint.'
)
@click.pass_context
def produce(ctx, log_level, prometheus_port):
    """Produce SAL messages for a specific set of SAL topics, or for all
    SAL topics with registered schemas.
    """
    configure_logging(level=log_level)


def configure_logging(level='info'):
    ch = logging.StreamHandler()
    formatter = logging.Formatter('%(message)s')
    ch.setFormatter(formatter)
    logger = logging.getLogger('kafkaefd')
    logger.addHandler(ch)
    logger.setLevel(getattr(logging, level.upper()))

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
