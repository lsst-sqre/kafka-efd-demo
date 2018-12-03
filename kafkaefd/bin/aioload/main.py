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

import aiohttp
import aiokafka
import click
import fastavro
import requests
from uritemplate import URITemplate
import structlog
from prometheus_client import Histogram, Counter, Summary
import prometheus_async.aio.web
from confluent_kafka.admin import AdminClient, NewTopic

from ..utils import get_registry_url, get_broker_url
from ...salschema.convert import validate_schema


CONSUMED = Counter('consumed', 'Topics consumed')
LATENCY = Histogram('consumer_latency_seconds', 'Consumer latency (seconds)')
LATENCY_SUMMARY = Summary('consumer_latency_summ_seconds',
                          'Consumer latency (seconds)')
PRODUCED = Counter('produced', 'Topics produced')


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


@aioload.command('init-topics')
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
def initialize_topics(ctx, root_name, count, log_level):
    """Initialize topics and synchronize Avro schemas to the registry.
    """
    configure_logging(level=log_level)
    structlog.get_logger(__name__).bind(
        role='init-topics',
    )

    schema_registry_url = get_registry_url(ctx.parent.parent)
    broker_url = get_broker_url(ctx.parent.parent)

    _create_topics(broker_url, root_name, count)
    _create_schemas(schema_registry_url, root_name, count)


def _create_topics(broker_url, root_name, count):
    logger = structlog.get_logger(__name__)
    settings = {'bootstrap.servers': broker_url}
    client = AdminClient(settings)

    names = [f'{root_name}{i}' for i in range(count)]

    topics = [NewTopic(name, num_partitions=1, replication_factor=1)
              for name in names]

    # Call create_topics to asynchronously create topics.
    # A dict of <topic,future> is returned.
    fs = client.create_topics(topics)

    # Wait for operation to finish.
    # Timeouts are preferably controlled by passing request_timeout=15.0
    # to the create_topics() call.
    # All futures will finish at the same time.
    for topic, f in fs.items():
        try:
            f.result()  # The result itself is None
            logger.info("Topic created", topic=topic)
        except Exception:
            logger.exception("Failed to create topic", topic=topic)


def _create_schemas(schema_registry_url, root_name, count):
    logger = structlog.get_logger(__name__)

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
    '--count', 'total_topic_count', type=int, default=1, show_default=True,
    help='Number of independent topics to produce. This count should match '
         'the number of schemas created with the upload-schemas command.'
)
@click.option(
    '--producer-count', 'total_producer_count', type=int, default=1,
    show_default=True,
    help='Total number of producers that are run.'
)
@click.option(
    '--producer-id', 'producer_id', type=int, default=0,
    show_default=True,
    help='Unique integer identifying the producer. If --producer-count=4, '
         'then producer-id can be 0, 1, 2, or 3. This ID is used as an offset '
         'to slice topics across all the producer nodes.'
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
@click.option(
    '--prometheus-port', 'prometheus_port', type=int, default=9092,
    help='Port for the Prometheus metrics scraping endpoint.'
)
@click.pass_context
def produce(ctx, root_topic_name, total_topic_count, total_producer_count,
            producer_id, hertz, log_level, prometheus_port):
    """Produce messages for one or more topics with a given frequency.

    This command is designed to produce messages for a set of related topics.
    The root topic name is the --name argument.

    **Single node usage**

    - Set --count to the total number of topics to produce for.
    - Set --producer-count=1 (default)
    - Set --producer-id=0 (default)

    **Multi-node usage**

    - Set --count to the total number of topics to produce for, across all
      nodes.
    - Set --producer-count to the total number of nodes.
    - Set --producer-id to a integer from 0 to producer-count-1. Each
      producer node needs to have a unique ID.
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
                      topic_count=total_topic_count,
                      period=period,
                      total_producer_count=total_producer_count,
                      producer_id=producer_id,
                      prometheus_port=prometheus_port)
    )


@aioload.command('consume')
@click.option(
    '--name',  'root_topic_name', type=click.Choice(['aioload-simple']),
    show_default=True, default='aioload-simple',
    help='Root topic name. This should match the --name argument for '
         'upload-schemas.'
)
@click.option(
    '--count', 'total_topic_count', type=int, default=1, show_default=True,
    help='Number of independent topics to produce. This count should match '
         'the number of schemas created with the upload-schemas command.'
)
@click.option(
    '--consumer-count', 'total_consumer_count', type=int, default=1,
    show_default=True,
    help='Total number of consumer nodes that are run.'
)
@click.option(
    '--consumer-id', 'consumer_id', type=int, default=0,
    show_default=True,
    help='Unique integer identifying the consumer node. If '
         '--consumer-count=4, then --consumer-id can be 0, 1, 2, or 3. '
         'This ID is used as an offset to slice topics across all the '
         'consumer nodes.'
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
def consume(ctx, root_topic_name, total_topic_count, total_consumer_count,
            consumer_id, log_level, prometheus_port):
    """Consume messages for a set of topics.
    """
    configure_logging(level=log_level)

    schema_registry_url = get_registry_url(ctx.parent.parent)
    consumer_settings = {
        'bootstrap_servers': get_broker_url(ctx.parent.parent),
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
                      total_topic_count=total_topic_count,
                      total_consumer_count=total_consumer_count,
                      consumer_id=consumer_id,
                      root_topic_name=root_topic_name,
                      prometheus_port=prometheus_port)
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
                        period, total_producer_count, producer_id,
                        prometheus_port):
    # Start the Prometheus endpoint
    asyncio.ensure_future(
        prometheus_async.aio.web.start_http_server(
            port=prometheus_port)
    )

    async with aiohttp.ClientSession() as httpsession:
        tasks = []
        # Create async tasks that generate different topics. The assignment
        # is done to systematically spread topics across multiple nodes, if
        # configured.
        # The range strides over the total number of producer nodes. But the
        # producer_id serves as an offset so that each producer node produces
        # different topics.
        for index in range(producer_id, topic_count, total_producer_count):
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
            PRODUCED.inc()  # increment prometheus production counter
            logger.debug('Sent message')
            # naieve message period; need to correct for production time
            await asyncio.sleep(period)
    finally:
        await producer.stop()


async def consumer_main(*, loop, consumer, root_consumer_settings,
                        root_topic_name, schema_registry_url,
                        prometheus_port, total_topic_count,
                        total_consumer_count, consumer_id):
    # Start the Prometheus endpoint
    asyncio.ensure_future(
        prometheus_async.aio.web.start_http_server(
            port=prometheus_port)
    )

    async with aiohttp.ClientSession() as httpsession:
        tasks = []
        # Stride over topics to evenly distribute them across all consumer
        # nodes.
        for index in range(consumer_id,
                           total_topic_count,
                           total_consumer_count):
            consumer_settings = dict(root_consumer_settings)
            topic_name = f'{root_topic_name}{index:d}'

            tasks.append(asyncio.ensure_future(
                consumer(loop=loop,
                         httpsession=httpsession,
                         consumer_settings=consumer_settings,
                         schema_registry_url=schema_registry_url,
                         topic_name=topic_name)
            ))
        await asyncio.gather(*tasks)


async def consume_for_simple_topics(*, loop, httpsession, consumer_settings,
                                    schema_registry_url, topic_name):
    consumer_settings.update({
        'group_id': topic_name,
        'client_id': f'{topic_name}-0'  # always only one consumer per topic
    })
    logger = structlog.get_logger(__name__).bind(
        role='consumer',
        group=consumer_settings['group_id'],
        client_id=consumer_settings['client_id']
    )
    logger.info(f'Getting schemas for topic {topic_name}')

    registry_headers = {'Accept': 'application/vnd.schemaregistry.v1+json'}
    schema_uri = URITemplate(
        schema_registry_url + '/subjects{/subject}/versions/latest'
    )

    # Get schemas
    r = await httpsession.get(
        schema_uri.expand(subject=f'{topic_name}-key'),
        headers=registry_headers)
    data = await r.json()
    key_schema = fastavro.parse_schema(json.loads(data['schema']))

    r = await httpsession.get(
        schema_uri.expand(subject=f'{topic_name}-value'),
        headers=registry_headers)
    data = await r.json()
    value_schema = fastavro.parse_schema(json.loads(data['schema']))

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
                    value_schema)
                now = datetime.datetime.now(datetime.timezone.utc)
                latency = now - value['timestamp']
                latency_millisec = \
                    latency.seconds * 1000 + latency.microseconds / 1000
                CONSUMED.inc()  # increment prometheus consumption counter
                LATENCY.observe(latency_millisec / 1000)
                LATENCY_SUMMARY.observe(latency_millisec / 1000)
                logger.debug(
                    'latency',
                    latency_millisec=latency_millisec,
                    topic=message.topic)
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
