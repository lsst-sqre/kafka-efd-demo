"""Implementation of the kafkaefd aioload commands for testing latency
in Kafka production and consumption under different loads (topic volume and
frequency).
"""

__all__ = ('aioload',)

import asyncio
import datetime
from io import BytesIO
import json
import logging
from pathlib import Path
import re

import aiohttp
import aiokafka
import click
import fastavro
import requests
from uritemplate import URITemplate
import structlog

from ..utils import get_registry_url, get_broker_url
from ...salschema.convert import validate_schema


@click.group()
@click.pass_context
def aioload(ctx):
    """Test kafka produce-consume latency under different topic population
    and frequency loads.

    Messages are consumed and produced asynchronously with aiokafka.
    """
    ctx.obj = {}


@aioload.command('test-schemas')
@click.pass_context
def test_schemas(ctx):
    """Test Avro schemas.
    """
    value_schema = fastavro.parse_schema(
        create_indexed_schema('aioload-simple-value', index=0))

    print('value schema:')
    print(json.dumps(value_schema, indent=2, sort_keys=True))

    value_binary = BytesIO()
    fastavro.schemaless_writer(
        value_binary,
        value_schema,
        {'timestamp': datetime.datetime.now()}
    )

    # read it back
    value_binary.seek(0)
    value_data = fastavro.schemaless_reader(
        value_binary, value_schema
    )
    print('Got value:')
    print(value_data)


@aioload.command('upload-schemas')
@click.option(
    '--name', 'root_name', type=click.Choice(['aioload-simple']),
    show_default=True, default='aioload-simple',
    help='Root name of the topic schema (without -value/-key and json '
         'extension.'
)
@click.option(
    '--count', type=int, default=1, show_default=True,
    help='Number of indexed schemas to generate. This is also the number of '
         'simultaneous topics that can be run.'
)
@click.option(
    '--log-level', 'log_level',
    type=click.Choice(['debug', 'info', 'warning']),
    default='info', help='Logging level'
)
@click.pass_context
def upload_schemas(ctx, root_name, count, log_level):
    """Synchronize Avro schemas to the registry.
    """
    configure_logging(level=log_level)
    logger = structlog.get_logger(__name__).bind(
        role='upload-schemas',
    )

    schema_registry_url = get_registry_url(ctx.parent.parent)

    session = requests.Session()
    session.headers.update({
        'Accept': 'application/vnd.schemaregistry.v1+json'
    })
    uri = URITemplate(schema_registry_url + '/subjects{/subject}/versions')

    for i in range(count):
        names = [f'{root_name}-key', f'{root_name}-value']
        subjects = [f'{root_name}{i:d}-key', f'{root_name}{i:d}-value']
        for name, subject in zip(names, subjects):
            schema = create_indexed_schema(name, index=i)
            data = {'schema': json.dumps(schema, sort_keys=True)}
            url = uri.expand({'subject': subject})
            r = session.post(url, json=data)
            data = r.json()
            r.raise_for_status()
            logger.info('Uploaded schema', subject=subject, id=data['id'])


@aioload.command('produce')
@click.option(
    '--name',  'root_topic_name', type=click.Choice(['aioload-simple']),
    show_default=True, default='aioload-simple',
    help='Root topic name. This should match the --name argument for '
         'upload-schemas.'
)
@click.option(
    '--count', type=int, default=1, show_default=True,
    help='Number of independent topics to produce. This count should match '
         'the number of schemas created with the upload-schemas command.'
)
@click.option(
    '--hertz', type=float, default=1., show_default=True,
    help="Frequency of messages (hertz)"
)
@click.option(
    '--log-level', 'log_level',
    type=click.Choice(['debug', 'info', 'warning']),
    default='info', help='Logging level'
)
@click.pass_context
def produce(ctx, root_topic_name, count, hertz, log_level):
    """Produce messages for a given topic with a given frequency.
    """
    configure_logging(level=log_level)

    schema_registry_url = get_registry_url(ctx.parent.parent)
    producer_settings = {
        'bootstrap_servers': get_broker_url(ctx.parent.parent),
    }

    period = 1. / hertz

    if root_topic_name == 'aioload-simple':
        producer = produce_for_simple_topic
    else:
        raise RuntimeError(f'No producer for topic {root_topic_name}')

    loop = asyncio.get_event_loop()
    loop.run_until_complete(
        producer_main(loop=loop,
                      producer=producer,
                      root_topic_name=root_topic_name,
                      root_producer_settings=producer_settings,
                      schema_registry_url=schema_registry_url,
                      topic_count=count,
                      period=period)
    )


@aioload.command('consume')
@click.option(
    '--name',  'root_topic_name', type=click.Choice(['aioload-simple']),
    show_default=True, default='aioload-simple',
    help='Root topic name. This should match the --name argument for '
         'upload-schemas.'
)
@click.option(
    '--count', 'consumer_count', type=int, default=1, show_default=True,
    help='Number of consumer threads to run.'
)
@click.option(
    '--log-level', 'log_level',
    type=click.Choice(['debug', 'info', 'warning']),
    default='info', help='Logging level'
)
@click.pass_context
def consume(ctx, root_topic_name, consumer_count, log_level):
    """Consume messages for a set of topics.
    """
    configure_logging(level=log_level)

    schema_registry_url = get_registry_url(ctx.parent.parent)
    consumer_settings = {
        'bootstrap_servers': get_broker_url(ctx.parent.parent),
        'group_id': root_topic_name,
        'auto_offset_reset': 'latest'
    }

    if root_topic_name == 'aioload-simple':
        consumer = consume_for_simple_topics
    else:
        raise RuntimeError(f'No consumer for topic {root_topic_name}')

    loop = asyncio.get_event_loop()
    loop.run_until_complete(
        consumer_main(loop=loop,
                      consumer=consumer,
                      root_consumer_settings=consumer_settings,
                      schema_registry_url=schema_registry_url,
                      consumer_count=consumer_count,
                      root_topic_name=root_topic_name)
    )


def create_indexed_schema(name, index=0):
    """Create a schema with an indexed namespace based on a template.

    This is useful for generating many instances of a schema that can be used
    by multiple topics in testing.

    Parameters
    ----------
    name : `str`
        Name, without ``.json`` suffix, of a schema file in the
        ``aioload/schemas`` directory.
    index : `int`
        Index to rename the output schema. For example, if the namespace is
        ``org.lsst.kafka_efd_demo.aioload.simple``, the new schema will have
        a namespace of ``org.lsst.kafka_efd_demo.aioload.simple0`` given an
        index of 0.

    Returns
    -------
    schema : `dict`
        Schema object with an indexed name.
    """
    source_path = Path(__file__).parent / 'schemas' / f"{name}.json"
    with source_path.open() as f:
        schema = json.load(f)
    schema['namespace'] += f'{index:d}'

    # validate the schema
    validate_schema(schema, raise_error=True)

    return schema


async def producer_main(*, loop, producer, root_producer_settings,
                        root_topic_name, schema_registry_url, topic_count,
                        period):
    async with aiohttp.ClientSession() as httpsession:
        tasks = []
        for index in range(topic_count):
            topic_name = f'{root_topic_name}{index:d}'
            producer_settings = dict(root_producer_settings)
            tasks.append(asyncio.ensure_future(
                producer(loop=loop,
                         httpsession=httpsession,
                         producer_settings=producer_settings,
                         schema_registry_url=schema_registry_url,
                         topic_name=topic_name,
                         period=period)
            ))
        await asyncio.gather(*tasks)


async def produce_for_simple_topic(*, loop, httpsession, producer_settings,
                                   schema_registry_url, topic_name, period):
    logger = structlog.get_logger(__name__).bind(
        role='producer',
        topic=topic_name,
    )

    logger.info('Getting schemas')
    schema_uri = URITemplate(
        schema_registry_url + '/subjects{/subject}/versions/latest'
    )
    headers = {
        'Accept': 'application/vnd.schemaregistry.v1+json'
    }

    # Get key schema
    r = await httpsession.get(
        schema_uri.expand(subject=topic_name + '-key'),
        headers=headers)
    data = await r.json()
    key_schema = fastavro.parse_schema(json.loads(data['schema']))

    # Get value schema
    r = await httpsession.get(
        schema_uri.expand(subject=topic_name + '-value'),
        headers=headers)
    data = await r.json()
    value_schema = fastavro.parse_schema(json.loads(data['schema']))

    default_key_fh = BytesIO()
    fastavro.schemaless_writer(default_key_fh, key_schema, {})
    default_key_fh.seek(0)
    default_key = default_key_fh.read()

    # Set up producer
    producer = aiokafka.AIOKafkaProducer(loop=loop, **producer_settings)
    await producer.start()
    logger.info(f'Started producer')

    try:
        while True:
            message_fh = BytesIO()
            fastavro.schemaless_writer(
                message_fh,
                value_schema,
                {'timestamp': datetime.datetime.now(datetime.timezone.utc)})
            message_fh.seek(0)
            # May want to adjust this control batching latency
            await producer.send_and_wait(
                topic_name, key=default_key, value=message_fh.read())
            logger.debug('Sent message')
            # naieve message period; need to correct for production time
            await asyncio.sleep(period)
    finally:
        await producer.stop()


async def consumer_main(*, loop, consumer, root_consumer_settings,
                        root_topic_name, schema_registry_url,
                        consumer_count):
    async with aiohttp.ClientSession() as httpsession:
        tasks = []
        for index in range(consumer_count):
            consumer_settings = dict(root_consumer_settings)
            consumer_settings['client_id'] = \
                consumer_settings['group_id'] + f'-{index:d}'

            tasks.append(asyncio.ensure_future(
                consumer(loop=loop,
                         httpsession=httpsession,
                         consumer_settings=consumer_settings,
                         schema_registry_url=schema_registry_url,
                         root_topic_name=root_topic_name)
            ))
        await asyncio.gather(*tasks)


async def consume_for_simple_topics(*, loop, httpsession, consumer_settings,
                                    schema_registry_url, root_topic_name):
    logger = structlog.get_logger(__name__).bind(
        role='consumer',
        group=consumer_settings['group_id'],
        client_id=consumer_settings['client_id']
    )
    logger.info(f'Getting schemas for root topic {root_topic_name}')

    registry_headers = {'Accept': 'application/vnd.schemaregistry.v1+json'}

    # Get names of subject for topic keys and values in the experiment
    r = await httpsession.get(
        schema_registry_url + '/subjects',
        headers=registry_headers)
    subject_names = await r.json()
    # Filter subjects to just ones that correspond to topics in the experiment
    subject_pattern = re.compile(
        r'^' + root_topic_name + r'[\d]+-((key)|(value))$')
    subject_names = [n for n in subject_names
                     if subject_pattern.match(n) is not None]

    # Get schemas for these subjects
    schemas = {}
    # This pattern extracts the topic name and whether it is a key or value
    # schema from the subject name
    general_subject_pattern = re.compile(
        r'^(?P<topic>[a-zA-Z0-9_\-\.]+)-(?P<type>(key)|(value))$')
    schema_uri = URITemplate(
        schema_registry_url + '/subjects{/subject}/versions/latest')
    for subject_name in subject_names:
        r = await httpsession.get(
            schema_uri.expand(subject=subject_name),
            headers=registry_headers)
        data = await r.json()
        schema = fastavro.parse_schema(json.loads(data['schema']))

        m = general_subject_pattern.match(subject_name)
        topic_name = m.group('topic')
        subject_type = m.group('type')
        logger.debug('Adding schema',
                     topic=topic_name,
                     subject_type=subject_type)
        if topic_name not in schemas:
            schemas[topic_name] = {'key': None, 'value': None}
        schemas[topic_name][subject_type] = schema

    # Start up the Kafka consumer
    consumer = aiokafka.AIOKafkaConsumer(loop=loop, **consumer_settings)

    # Main loop for consuming messages
    try:
        await consumer.start()

        # Subscribe to all topics in the experiment
        topic_pattern = r'^' + root_topic_name + r'[\d]+$'
        consumer.subscribe(pattern=topic_pattern)

        # await consumer.seek_to_end()

        logger.info(f'Started consumer for topic pattern {topic_pattern}')
        while True:
            async for message in consumer:
                value_fh = BytesIO(message.value)
                value_fh.seek(0)
                value = fastavro.schemaless_reader(
                    value_fh,
                    schemas[message.topic]['value'])
                now = datetime.datetime.now(datetime.timezone.utc)
                latency = now - value['timestamp']
                logger.debug(
                    'latency',
                    latency_millisec=latency.microseconds / 1000)
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
