"""Transform text-formatted messages from the SAL into Avro-formatted
messages for Kafka connect.
"""

__all__ = ('saltransform',)

import asyncio
import datetime
import time
import re
import logging

import aiohttp
import aiokafka
import click
import structlog
from confluent_kafka.admin import AdminClient, NewTopic
from prometheus_client import Counter, Summary
import prometheus_async.aio.web

from kafkit.registry.serializer import PolySerializer
from kafkit.registry.aiohttp import RegistryApi

from ..salschema.repo import SalXmlRepo
from ..salschema.convert import convert_topic
from .utils import get_registry_url, get_broker_url

# Prometheus metrics
PRODUCED = Counter(
    'saltransform_produced',
    'Messages produced by kafkaefd saltransform.')
TOTAL_TIME = Summary(
    'saltransform_total_seconds',
    'Total message processing time, in seconds.')
TRANSFORM_TIME = Summary(
    'saltransform_transform_seconds',
    'Time to transform text to Avro, in seconds.')


@click.group('saltransform')
@click.pass_context
def saltransform(ctx):
    """Transform SAL topics with plain-text messages into a new set of topics
    with Avro-encoded messages.
    """
    ctx.obj = {}


@saltransform.command('init')
@click.option(
    '--subsystem', 'subsystems', multiple=True, required=True,
    help='A subsystem to monitor. SAL currently emits all messages for '
         'a subsystem on a single topic named after that subsystem. Provide '
         'several subsystem options to simultaneously monitor multiple '
         'subssytems.'
)
@click.option(
    '--xml-repo', 'xml_repo_slug',
    default='lsst-ts/ts_xml', show_default=True,
    help='Slug of the ``ts_xml`` GitHub repository slug containing the SAL'
         'XML topic schemas.'
)
@click.option(
    '--xml-repo-ref', 'xml_repo_ref',
    default='develop', show_default=True,
    help='Tag of branch name of the ``ts_xml`` GitHub repository.'
)
@click.option(
    '--github-user', '-u', 'github_username',
    envvar='GITHUB_USER',
    help='GitHub username for authenticating to the GitHub API. '
         'Alternative set with the $GITHUB_USER environment variable.'
)
@click.option(
    '--github-token', '-t', 'github_token',
    envvar='GITHUB_TOKEN',
    help='GitHub personal access token for authenticating to the GitHub API. '
         'Set this option with the $GITHUB_TOKEN environment variable for '
         'better security.'
)
@click.option(
    '--replication', 'replication_factor', type=int, default=3,
    show_default=True,
    help='Replication factor configulation for topics.'
)
@click.option(
    '--partitions', 'partitions', type=int, default=1, show_default=True,
    help='Number of partitions per topic. Note: messages are not produced '
         'with a key, so there is effectively no partitioning.'
)
@click.pass_context
def init(ctx, subsystems, xml_repo_slug, xml_repo_ref, github_username,
         github_token, replication_factor, partitions):
    """Initialize topics and schemas.
    """
    loop = asyncio.get_event_loop()
    loop.run_until_complete(
        main_init(
            loop=loop,
            subsystems=subsystems,
            xml_repo_slug=xml_repo_slug,
            xml_repo_ref=xml_repo_ref,
            github_username=github_username,
            github_token=github_token,
            registry_url=get_registry_url(ctx.parent.parent),
            broker_url=get_broker_url(ctx.parent.parent),
            replication_factor=replication_factor,
            partitions=partitions
        )
    )


@saltransform.command('run')
@click.option(
    '--subsystem', 'subsystems', multiple=True, required=True,
    help='A subsystem to monitor. SAL currently emits all messages for '
         'a subsystem on a single topic named after that subsystem. Provide '
         'several subsystem options to simultaneously monitor multiple '
         'subssytems.'
)
@click.option(
    '--log-level', 'log_level',
    type=click.Choice(['debug', 'info', 'warning']),
    default='info', help='Logging level'
)
@click.option(
    '--auto-offset-reset', 'auto_offset_reset',
    type=click.Choice(['latest', 'earliest']), default='latest',
    help='If the group does not have a committed offset, this option '
         'defines how the consumer proceeds. "earliest" means that the '
         'consumer begins from the first offset. "latest" means the consumer '
         'begins with the next message that is added to the topic after the '
         'consumer is started.'
)
@click.option(
    '--rewind-to-start', 'rewind_to_start', is_flag=True,
    default=False,
    help='Rewind each consumer to the start of its partition. '
         'This overrides the --auto-offset-reset option.'
)
@click.option(
    '--prometheus-port', 'prometheus_port', type=int, default=9092,
    help='Port for the Prometheus metrics scraping endpoint.'
)
@click.pass_context
def run(ctx, subsystems, log_level, auto_offset_reset, rewind_to_start,
        prometheus_port):
    """Run a Kafka producer-consumer that consumes messages plain text
    messages from the SAL and produces Avro-encoded messages.
    """
    configure_logging(level=log_level)
    structlog.get_logger(__name__).bind(
        command='run'
    )

    producer_settings = {
        'bootstrap_servers': get_broker_url(ctx.parent.parent),
    }
    consumer_settings = {
        'bootstrap_servers': get_broker_url(ctx.parent.parent),
        'auto_offset_reset': auto_offset_reset
    }

    loop = asyncio.get_event_loop()
    loop.run_until_complete(
        main_runner(
            loop=loop,
            subsystems=subsystems,
            consumer_settings=consumer_settings,
            producer_settings=producer_settings,
            registry_url=get_registry_url(ctx.parent.parent),
            rewind_to_start=rewind_to_start,
            prometheus_port=prometheus_port
        )
    )


async def main_init(*, loop, subsystems, xml_repo_slug,
                    xml_repo_ref, github_username, github_token,
                    registry_url, broker_url, replication_factor, partitions):
    conn = aiohttp.TCPConnector(limit_per_host=20)
    async with aiohttp.ClientSession(connector=conn) as httpsession:
        xml_org, xml_repo_name = xml_repo_slug.split('/')
        xmlRepo = await SalXmlRepo.from_github(
            httpsession,
            github_org=xml_org,
            github_repo=xml_repo_name,
            git_ref=xml_repo_ref,
            github_user=github_username,
            github_token=github_token)

        registry = RegistryApi(session=httpsession, url=registry_url)

        tasks = []
        topic_names = []
        for subsystem in subsystems:
            for _, topic in xmlRepo.itersubsystem(subsystem):
                schema = convert_topic(topic)
                if 'namespace' in schema:
                    name = f'{schema["namespace"]}.{schema["name"]}'
                else:
                    name = schema["name"]
                topic_names.append(name)
                tasks.append(
                    asyncio.ensure_future(
                        registry.register_schema(schema)
                    )
                )
        await asyncio.gather(*tasks)

        # Create corresponding Kafka topics, if necessary
        broker = AdminClient({'bootstrap.servers': broker_url})
        existing_topic_names = [
            t for t in broker.list_topics(timeout=10).topics.keys()]
        topic_names = [t for t in topic_names
                       if t not in existing_topic_names]
        if len(topic_names) > 0:
            new_topics = [NewTopic(topic, num_partitions=partitions,
                                   replication_factor=replication_factor)
                          for topic in topic_names]
            fs = broker.create_topics(new_topics)
            for topic, f in fs.items():
                try:
                    f.result()  # The result itself is None
                    print("Topic {} created".format(topic))
                except Exception as e:
                    print("Failed to create topic {}: {}".format(topic, e))


async def main_runner(*, loop, subsystems, consumer_settings,
                      producer_settings, registry_url, rewind_to_start,
                      prometheus_port):
    # Start the Prometheus endpoint
    asyncio.ensure_future(
        prometheus_async.aio.web.start_http_server(
            port=prometheus_port)
    )

    tasks = []
    async with aiohttp.ClientSession() as httpsession:
        for subsystem in subsystems:
            for kind in ('command', 'event', 'telemetry'):
                tasks.append(asyncio.ensure_future(
                    subsystem_transformer(
                        loop=loop,
                        subsystem=subsystem,
                        kind=kind,
                        httpsession=httpsession,
                        registry_url=registry_url,
                        producer_settings=producer_settings,
                        consumer_settings=consumer_settings,
                        rewind_to_start=rewind_to_start
                    )
                ))
        await asyncio.gather(*tasks)


async def subsystem_transformer(*, loop, subsystem, kind, httpsession,
                                registry_url,
                                consumer_settings, producer_settings,
                                rewind_to_start):
    logger = structlog.get_logger(__name__).bind(
        subsystem=subsystem,
        kind=kind
    )

    consumer_settings = consumer_settings.copy()

    logger.info('Setting up transformer')

    registry = RegistryApi(session=httpsession, url=registry_url)
    transformer = SalTextTransformer(registry)

    logger.info('Built transformer class')

    # Start the consumer and the producer
    producer = aiokafka.AIOKafkaProducer(loop=loop, **producer_settings)
    await producer.start()
    logger.info('Started producer', **producer_settings)

    input_topic_name = f"{subsystem}_{kind}"

    consumer_settings = consumer_settings.copy()
    consumer_settings['group_id'] = input_topic_name
    consumer = aiokafka.AIOKafkaConsumer(loop=loop, **consumer_settings)

    try:
        await consumer.start()
        logger.info('Started consumer', **consumer_settings)

        # SAL produces to Kafka topics named after subsystem and kind
        consumer.subscribe([input_topic_name])

        partitions = consumer.assignment()
        while len(partitions) == 0:
            # Wait for the consumer to get partition assignment
            await asyncio.sleep(1.)
            partitions = consumer.assignment()

        logger.info(
            'Initial partition assignment',
            topic=input_topic_name,
            partitions=[str(p) for p in partitions])

        if rewind_to_start:
            await consumer.seek_to_beginning()
            logger.info('Rewound to beginning')

        for partition in partitions:
            offset = await consumer.position(partition)
            logger.info('Initial offset',
                        partition=str(partition), offset=offset)

        while True:
            async for inbound_message in consumer:
                task = asyncio.ensure_future(process_message(
                                             inbound_message=inbound_message,
                                             transformer=transformer,
                                             producer=producer,
                                             logger=logger))
                await task
    finally:
        logger.info('Shutting down')
        consumer.stop()
        logger.info('Shutdown complete')


async def process_message(inbound_message, transformer, producer, logger):
    start_time = time.perf_counter()
    logger.debug(
        'got message',
        message=inbound_message.value,
        key=inbound_message.key)
    try:
        inbound_key = inbound_message.key.decode('utf-8')
    except AttributeError:
        # Key is None and can't be decoded
        inbound_key = ""
    try:
        inbound_value = inbound_message.value.decode('utf-8')
    except AttributeError:
        # Value is None and can't be decoded
        inbound_value = ""

    transform_start_time = time.perf_counter()
    schema_name, outbound_message = await transformer.transform(
        inbound_key, inbound_value)

    transform_time = time.perf_counter() - transform_start_time

    TRANSFORM_TIME.observe(transform_time)

    # Use the fully-qualified schema name as the topic name
    # for the outbound stream.
    await producer.send_and_wait(
        schema_name, value=outbound_message)

    total_time = time.perf_counter() - start_time

    logger.debug(f'Transform time: {transform_time:0.6f}s')
    logger.debug(f'Total time: {total_time:0.6f}s')

    PRODUCED.inc()

    TOTAL_TIME.observe(total_time)


class SalTextTransformer:
    """A class that transforms text-formatted SAL messages to Avro.
    """

    preamble_pattern = re.compile(
        r"^(?P<subsystem>\w+) "
        r"(?P<topic_name>\w+):\( "
        r"(?P<content>[\'\w\d\s,\.-]+)\)"
    )

    def __init__(self, registry):
        super().__init__()
        self._registry = registry
        self._serializer = PolySerializer(registry=self._registry)

    async def transform(self, key_text, message_text):
        """Transform the message to Confluent Wire Format Avro.
        """
        m = self.preamble_pattern.match(message_text)
        if m is None:
            raise RuntimeError('Cannot match topic name')

        topic_name = m.group('topic_name')

        schema_info = await self._registry.get_schema_by_subject(
            # Subjects are fully namespaced as lsst.sal.
            f"lsst.sal.{topic_name}",
            version='latest'
        )

        items = [s.strip(" '") for s in m.group('content').split(',')]

        avro_data = {}

        # Add data from the SAL preamble
        avro_data['sal_revcode'] = items[0]
        avro_data['sal_created'] = datetime.datetime.fromtimestamp(
            float(items[1]), tz=datetime.timezone.utc)
        avro_data['sal_ingested'] = datetime.datetime.fromtimestamp(
            float(items[2]), tz=datetime.timezone.utc)
        avro_data['sal_sequence'] = int(items[3])
        avro_data['sal_host'] = int(items[4])
        avro_data['sal_origin'] = int(items[5])

        # Timestamp when this Kafka app is processing the message.
        avro_data['kafka_timestamp'] = datetime.datetime.now(
            datetime.timezone.utc)

        # Scan the data corresponding to the SAL XML schema.
        data_items = items[6:]
        scan_index = 0
        for schema_field in schema_info['schema']['fields']:
            if 'sal_index' not in schema_field:
                continue
            field_data, scan_index = scan_field(
                schema_field, scan_index, data_items)
            avro_data[schema_field['name']] = field_data

        message = await self._serializer.serialize(
            avro_data,
            schema=schema_info['schema'],
            schema_id=schema_info['id'],
            subject=schema_info['subject'])

        return schema_info['schema']['name'], message


def scan_field(schema_field, scan_index, data_items):
    scanner = get_scanner(schema_field)
    return scanner(schema_field, scan_index, data_items)


def scan_string(schema_field, scan_index, data_items):
    return data_items[scan_index].strip('"\' '), scan_index + 1


def scan_bytes(schema_field, scan_index, data_items):
    # I actually don't know if this is the right approach. data items are
    # decoded to utf-8, so maybe it makes sense to re-encode to get it back
    # to bytes?
    return data_items[scan_index].encode('utf-8'), scan_index + 1


def scan_boolean(schema_field, scan_index, data_items):
    return bool(data_items[scan_index]), scan_index + 1


def scan_int(schema_field, scan_index, data_items):
    return int(data_items[scan_index]), scan_index + 1


def scan_float(schema_field, scan_index, data_items):
    return float(data_items[scan_index]), scan_index + 1


def scan_timestamp_millis(schema_field, scan_index, data_items):
    timestamp = float(data_items[scan_index]) / 1000.
    dt = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)
    return dt, scan_index + 1


def scan_array(schema_field, scan_index, data_items):
    count = schema_field['type']['sal_count']
    item_type = schema_field['type']['items']
    scanner = get_scanner(type_=item_type)
    arr = []
    for _ in range(count):
        item, scan_index = scanner(schema_field, scan_index, data_items)
        arr.append(item)
    return arr, scan_index


SCANNERS = {
    'string': scan_string,
    'int': scan_int,
    'long': scan_int,
    'short': scan_int,
    'long long': scan_int,
    'unsigned short': scan_int,
    'unsigned int': scan_int,
    'unsigned long': scan_int,
    'unsigned long long': scan_int,
    'float': scan_float,
    'double': scan_float,
    'boolean': scan_boolean,
    'bytes': scan_bytes,
    'char': scan_bytes,
    'octet': scan_bytes,
}


def get_scanner(schema_field=None, type_=None):
    if type_ is None:
        type_ = schema_field['type']
    try:
        return SCANNERS[type_]
    except (KeyError, TypeError):
        if isinstance(type_, dict):
            if type_['type'] == 'long' and type_['type'] == 'timestamp-millis':
                return scan_timestamp_millis
            elif type_['type'] == 'array':
                return scan_array
            elif type_['type'] == 'enum':
                # TODO we think enums look like strings in the SAL messages,
                # but this isn't actually seen in the wild yet.
                return scan_string
            else:
                raise NotImplementedError(
                    "Don't know how to scan this array field yet: "
                    f"{schema_field!r}")


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
