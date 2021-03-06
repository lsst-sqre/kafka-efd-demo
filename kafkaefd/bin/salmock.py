"""Mock SAL producers.
"""

__all__ = ('salmock',)

import asyncio
import logging
import random
import datetime
import json
import struct
from io import BytesIO

import aiohttp
import aiokafka
import click
import fastavro
import structlog
from prometheus_client import Counter
import prometheus_async.aio.web
from uritemplate import URITemplate

from .utils import get_registry_url, get_broker_url

# required by confluent wire format
MAGIC_BYTE = 0

# Prometheus metrics
PRODUCED = Counter(
    'salmock_produced',
    'Topics produced by mock SAL')


@click.group()
@click.pass_context
def salmock(ctx):
    """Mock SAL producers.
    """
    ctx.obj = {}


@salmock.command()
@click.option(
    '--topic', 'topic_names', multiple=True, show_default=True,
    help='Name of a SAL topic. Provider serveral --topic options to produce '
         'for several SAL topics. Leave out the --topic option entirely to '
         'autodiscover SAL topics based on the Schema Registry and produce '
         'for all those topics.'
)
@click.option(
    '--max-topics', type=int, default=None, show_default=True,
    help='Maximum number of topics to produce. This is useful when --topic is '
         'not set, but you don\'t want to produce for **all** the SAL topics.'
)
@click.option(
    '--period', type=float, default=1, show_default=True,
    help='Set the period in seconds in which every topic is produced, e.g. if '
         '--period is 0.1 topics are produced at 10Hz.'
)
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
def produce(ctx, topic_names, max_topics, period, log_level, prometheus_port):
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
            root_producer_settings=producer_settings,
            max_topics=max_topics,
            period=period)
    )


@salmock.command()
@click.argument('topic_name')
@click.option(
    '--log-level', 'log_level',
    type=click.Choice(['debug', 'info', 'warning']),
    default='info', help='Logging level'
)
@click.pass_context
def consume(ctx, topic_name, log_level):
    """Consume a single topic, printing messages to logging.
    """
    configure_logging(level=log_level)

    schema_registry_url = get_registry_url(ctx.parent.parent)
    consumer_settings = {
        'bootstrap_servers': get_broker_url(ctx.parent.parent),
        'auto_offset_reset': 'latest'
    }

    loop = asyncio.get_event_loop()
    loop.run_until_complete(
        consumer_main(
            loop=loop,
            topic_name=topic_name,
            consumer_settings=consumer_settings,
            schema_registry_url=schema_registry_url
        )
    )


async def producer_main(topic_names=None, *, max_topics, period, loop,
                        prometheus_port, schema_registry_url,
                        root_producer_settings):
    """Main asyncio-based function for the producer."""
    logger = structlog.get_logger(__name__)

    # Start the Prometheus endpoint
    asyncio.ensure_future(
        prometheus_async.aio.web.start_http_server(
            port=prometheus_port)
    )

    conn = aiohttp.TCPConnector(limit_per_host=20)
    async with aiohttp.ClientSession(connector=conn) as httpsession:
        if len(topic_names) == 0:
            # autodiscover topic names
            logger.debug('Autodiscovering topics')
            topic_names = await autodiscover_topics(httpsession,
                                                    schema_registry_url)

        # Make topic names compatible with Kafka
        topic_names = [n.replace('_', '-').lower() for n in topic_names]

        # Ensure uniqueness
        topic_names = list(set(topic_names))

        # Sort
        topic_names.sort()

        # Subset topic list
        if max_topics is not None:
            if len(topic_names) > max_topics:
                topic_names = topic_names[:max_topics]

        logger.debug('Identified topics', topics=topic_names)

        # Get schemas for topics
        # NOTE: if we auto-discovered topics we downloaded schemas, so there's
        # room for optimization here.
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
                schema=schema[0],
                schema_id=schema[1],
                period=period
            )
        )
    await asyncio.gather(*tasks)


async def autodiscover_topics(httpsession, schema_registry_url):
    logger = structlog.get_logger(__name__)
    headers = {
        'Accept': 'application/vnd.schemaregistry.v1+json'
    }

    # List all subjects in the registry
    list_uri = schema_registry_url + '/subjects'
    r = await httpsession.get(list_uri, headers=headers)
    subject_names = await r.json()
    logger.debug(
        'autodiscover_topics found all subjects',
        length=len(subject_names))

    # Get all the schemas to find ones that are SAL schemas
    tasks = []
    for subject_name in subject_names:
        tasks.append(
            asyncio.ensure_future(
                get_schema(subject_name, httpsession, schema_registry_url)
            )
        )
    results = await asyncio.gather(*tasks)

    # Get topic names corresponding to SAL schemas
    topic_names = []
    for subject_name, schema in zip(subject_names, results):
        # Heuristic for identifying a SAL schema. Actually probably
        # want to use namespace instead, but lsst.sal isn't formalized yet.
        if 'sal_topic_type' in schema[0]:
            nameparts = subject_name.split('-')
            if nameparts[-1] in ('value', 'key'):
                topic_names.append('-'.join(nameparts[:-1]))
                logger.debug(
                    'autodiscover topic accepted',
                    subject=subject_name)
            else:
                # unlikely code path?
                topic_names.append(subject_name)
                logger.debug(
                    'autodiscover topic accepted',
                    subject=subject_name)
        else:
            logger.debug(
                'autodiscover topic rejected',
                subject=subject_name)
    return topic_names


async def get_schema(subject_name, httpsession, host):
    headers = {
        'Accept': 'application/vnd.schemaregistry.v1+json'
    }
    uri_temp = URITemplate(host + '/subjects{/subject}/versions{/version}')
    uri = uri_temp.expand(subject=subject_name, version='latest')
    r = await httpsession.get(uri, headers=headers)
    data = await r.json()
    schema = json.loads(data['schema'])
    schema_id = data['id']
    return schema, schema_id


async def produce_for_topic(*, loop, producer_settings, topic_name, schema,
                            schema_id, period):
    logger = structlog.get_logger().bind(topic=topic_name)

    # Preparse schema
    schema = fastavro.parse_schema(schema)
    logger.info('Preparsed schema')

    # Start up the producer
    producer = aiokafka.AIOKafkaProducer(loop=loop, **producer_settings)
    await producer.start()
    logger.info('Started producer')

    # Generate and write messages
    try:
        for message in generate_message(schema):
            logger.debug('New message', message=message)
            message_fh = BytesIO()
            message_fh.write(struct.pack('>bI', MAGIC_BYTE, schema_id))
            fastavro.schemaless_writer(
                message_fh,
                schema,
                message
            )
            message_fh.seek(0)
            await producer.send_and_wait(
                topic_name, value=message_fh.read())
            # increment prometheus production counter
            PRODUCED.inc()
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
        field_generators[field['name']] = get_field_generator(field)

    # Generate random messages infinitely
    while True:
        message = {n: gen() for n, gen in field_generators.items()}
        logger.debug(message=message)
        yield message


def get_field_generator(field_schema):
    """Get the field value generator function corresponding to the schema
    for a single field.
    """
    logger = structlog.get_logger(__name__)
    logger.debug('Making field generator', field=field_schema['name'])
    if isinstance(field_schema['type'], str):
        # Basic field types
        return _get_primative_generator(field_schema['type'])

    elif isinstance(field_schema['type'], dict):
        # Complex field types
        if 'logicalType' in field_schema['type']:
            if field_schema['type']['logicalType'].startswith('timestamp'):
                return generate_timestamp

        elif 'type' in field_schema['type']:
            if field_schema['type']['type'] == 'enum':
                return EnumGenerator(
                    field_schema['type']['symbols'])
            elif field_schema['type']['type'] == 'array':
                item_gen = _get_primative_generator(
                    field_schema['type']['items'])
                return ArrayGenerator(item_gen)

    logger.error('Don\'t have generator for field type',
                 field=field_schema)
    raise RuntimeError


def _get_primative_generator(item_type):
    """Get the generator function for an int, long, float, bytes, string,
    or boolean type.
    """
    logger = structlog.get_logger(__name__)
    if item_type in ('int', 'long'):
        return generate_int
    elif item_type in ('float', 'double'):
        return generate_float
    elif item_type == 'bytes':
        return generate_bytes
    elif item_type == 'string':
        return generate_str
    elif item_type == 'boolean':
        return generate_bool
    else:
        logger.error('Don\'t have generator for field/item type',
                     item_type=item_type)
        raise RuntimeError


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


class ArrayGenerator:
    """Callable that generates array values of a given type.
    """

    def __init__(self, item_generator, length=2):
        self.length = length
        self.item_generator = item_generator

    def __call__(self):
        return [self.item_generator() for _ in range(self.length)]


async def consumer_main(*, loop, topic_name, consumer_settings,
                        schema_registry_url):
    """Main asyncio-based function for the single-topic consumer.
    """
    logger = structlog.get_logger(__name__)

    topic_name = topic_name.replace('_', '-').lower()

    async with aiohttp.ClientSession() as httpsession:
        schema, schema_id = await get_schema(
            topic_name + '-value',
            httpsession,
            schema_registry_url)

    # Start up the Kafka consumer
    consumer = aiokafka.AIOKafkaConsumer(loop=loop, **consumer_settings)

    # Main loop for consuming messages
    try:
        await consumer.start()

        # Subscribe to all topics in the experiment
        consumer.subscribe([topic_name])
        logger.info(f'Started consumer for topic {topic_name}')

        while True:
            async for message in consumer:
                value_fh = BytesIO(message.value)
                value_fh.seek(0)
                value = fastavro.schemaless_reader(
                    value_fh,
                    schema)
                logger.info("Received message", message=value)
    finally:
        consumer.stop()


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
