"""Mock SAL producers.
"""

__all__ = ('salmock',)

import asyncio
import logging
import random
import datetime
import json
from io import BytesIO

import aiohttp
import aiokafka
import click
import fastavro
import structlog
import prometheus_async.aio.web
from uritemplate import URITemplate

from .utils import get_registry_url, get_broker_url


@click.group()
@click.pass_context
def salmock(ctx):
    """Mock SAL producers.
    """
    ctx.obj = {}


@salmock.command()
@click.option('--topic', 'topic_names', multiple=True)
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
def produce(ctx, topic_names, log_level, prometheus_port):
    """Produce SAL messages for a specific set of SAL topics, or for all
    SAL topics with registered schemas.
    """
    configure_logging(level=log_level)

    schema_registry_url = get_registry_url(ctx.parent.parent)

    producer_settings = {
        'bootstrap_servers': get_broker_url(ctx.parent.parent),
    }

    loop = asyncio.get_event_loop()
    loop.run_until_complete(
        producer_main(
            loop=loop,
            prometheus_port=prometheus_port,
            schema_registry_url=schema_registry_url,
            topic_names=topic_names,
            root_producer_settings=producer_settings)
    )


async def producer_main(topic_names=None, *, loop, prometheus_port,
                        schema_registry_url, root_producer_settings):
    """Main asyncio-based function for the producer."""
    # Start the Prometheus endpoint
    asyncio.ensure_future(
        prometheus_async.aio.web.start_http_server(
            port=prometheus_port)
    )

    conn = aiohttp.TCPConnector(limit_per_host=20)
    async with aiohttp.ClientSession(connector=conn) as httpsession:
        if topic_names is None:
            # autodiscover topic names
            raise NotImplementedError

        # Make topic names compatible with Kafka
        topic_names = [n.replace('_', '-').lower() for n in topic_names]

        # Get schemas for topics
        tasks = []
        for name in topic_names:
            tasks.append(
                asyncio.ensure_future(
                    get_schema(
                        name + '-value',
                        httpsession,
                        schema_registry_url)))
        results = await asyncio.gather(*tasks)
        schemas = {name: schema for name, schema in zip(topic_names, results)}

    # Launch producers for each topic
    tasks = []
    for topic_name, schema in schemas.items():
        producer_settings = dict(root_producer_settings)
        tasks.append(
            produce_for_topic(
                loop=loop,
                producer_settings=producer_settings,
                topic_name=topic_name,
                schema=schema,
                period=1
            )
        )
    await asyncio.gather(*tasks)


async def get_schema(subject_name, httpsession, host):
    headers = {
        'Accept': 'application/vnd.schemaregistry.v1+json'
    }
    uri_temp = URITemplate(host + '/subjects{/subject}/versions{/version}')
    uri = uri_temp.expand(subject=subject_name, version='latest')
    r = await httpsession.get(uri, headers=headers)
    data = await r.json()
    return json.loads(data['schema'])


async def produce_for_topic(*, loop, producer_settings, topic_name, schema,
                            period):
    logger = structlog.get_logger().bind(topic=topic_name)

    # Preparse schema
    schema = fastavro.parse_schema(schema)

    # Start up the producer
    producer = aiokafka.AIOKafkaProducer(loop=loop, **producer_settings)
    await producer.start()
    logger.info('Started producer')

    # Generate and write messages
    try:
        for message in generate_message(schema):
            logger.debug('New message', message=message)
            message_fh = BytesIO()
            fastavro.schemaless_writer(
                message_fh,
                schema,
                message
            )
            message_fh.seek(0)
            await producer.send_and_wait(
                topic_name, value=message_fh.read())
            logger.debug('Sent message')
            # naieve message period; need to correct for production time
            await asyncio.sleep(period)
    finally:
        await producer.stop()


def generate_message(schema):
    """Generate mock messages for an Avro schema.

    Parameters
    ----------
    schema : `dict`
        Avro schema as a deserialized `dict`.

    Yields
    ------
    message : `dict`
        A message with random values appropriate to each fields's type.
    """
    logger = structlog.get_logger(__name__).bind(
        schema=schema['name']
    )

    # Make random value generators for each field, according to the field's
    # type.
    field_generators = {}
    for field in schema['fields']:
        logger.debug('Making field generator', field=field['name'])
        name = field['name']
        if isinstance(field['type'], str):
            # Basic field types
            if field['type'] in ('int', 'long'):
                field_generators[name] = generate_int
            elif field['type'] == 'float':
                field_generators[name] = generate_float
            elif field['type'] == 'bytes':
                field_generators[name] = generate_bytes
            elif field['type'] == 'string':
                field_generators[name] = generate_str
            elif field['type'] == 'boolean':
                field_generators[name] = generate_bool
            else:
                logger.error('Don\'t have generator for field type',
                             field=name)
                raise RuntimeError

        elif isinstance(field['type'], dict):
            # Complex field types
            if 'logicalType' in field['type']:
                if field['type']['logicalType'].startswith('timestamp'):
                    field_generators[name] = generate_timestamp

            elif 'type' in field['type']:
                if field['type']['type'] == 'enum':
                    field_generators[name] = EnumGenerator(
                        field['type']['symbols'])

            else:
                logger.error('Don\'t have generator for field type',
                             field=field)
                raise RuntimeError

        else:
            logger.error('Don\'t have generator for field type',
                         field=field)
            raise RuntimeError

    # Generate random messages infinitely
    while True:
        message = {n: gen() for n, gen in field_generators.items()}
        logger.debug(message=message)
        yield message


def generate_bool():
    """Generate a boolean, randomly."""
    return random.choice((True, False))


def generate_int():
    """Generate an integer, randomly."""
    return random.randint(0, 10)


def generate_float():
    """Generate a float, randomly."""
    return random.random()


def generate_bytes():
    """Generate bytes, randomly."""
    # Not sure what do generate for bytes. This is just zero-filled
    return bytes(2)


def generate_str():
    """Generate a string, randomly."""
    return random.choice(
        ('James', 'Mary', 'John', 'Patricia', 'Robert', 'Jennifer',
         'Michael', 'Linda', 'William', 'Elizabeth')
    )


def generate_timestamp():
    """Generate a timestamp that matches the current time."""
    return datetime.datetime.now(datetime.timezone.utc)


class EnumGenerator:
    """Callable that creates values from a enumeration."""

    def __init__(self, symbols):
        self.symbols = symbols

    def __call__(self):
        return random.choice(self.symbols)


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
