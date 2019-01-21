"""Transform text-formatted messages from the SAL into Avro-formatted
messages for Kafka connect.
"""

__all__ = ('saltransform',)

import asyncio
import datetime
import re
import logging

import aiohttp
import aiokafka
import click
import structlog

from kafkit.registry.serializer import PolySerializer
from kafkit.registry.aiohttp import RegistryApi

from .utils import get_registry_url, get_broker_url


@click.group('saltransform')
@click.pass_context
def saltransform(ctx):
    """Transform SAL topics with plain-text messages into a new set of topics
    with Avro-encoded messages.
    """
    ctx.obj = {}


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
@click.pass_context
def run(ctx, subsystems, log_level):
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
        'auto_offset_reset': 'latest'
    }

    loop = asyncio.get_event_loop()
    loop.run_until_complete(
        main_runner(
            loop=loop,
            subsystems=subsystems,
            consumer_settings=consumer_settings,
            producer_settings=producer_settings,
            registry_url=get_registry_url(ctx.parent.parent)
        )
    )


async def main_runner(*, loop, subsystems, consumer_settings,
                      producer_settings, registry_url):
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
                        consumer_settings=consumer_settings
                    )
                ))
        await asyncio.gather(*tasks)


async def subsystem_transformer(*, loop, subsystem, kind, httpsession,
                                registry_url,
                                consumer_settings, producer_settings):
    logger = structlog.get_logger(__name__).bind(
        subsystem=subsystem,
        kind=kind
    )

    logger.info('Setting up transformer')

    registry = RegistryApi(session=httpsession, url=registry_url)
    transformer = SalTextTransformer(registry)

    logger.info('Built transformer class')

    # Start the consumer and the producer
    producer = aiokafka.AIOKafkaProducer(loop=loop, **producer_settings)
    await producer.start()
    logger.info('Started producer', **producer_settings)

    consumer = aiokafka.AIOKafkaConsumer(loop=loop, **consumer_settings)

    try:
        await consumer.start()
        logger.info('Started consumer', **consumer_settings)

        # SAL produces to Kafka topics named after subsystem and kind
        consumer.subscribe([f'{subsystem}_{kind}'])

        while True:
            async for inbound_message in consumer:
                schema_name, outbound_message = await transformer.transform(
                    inbound_message.key.decode('utf-8'),
                    inbound_message.value.decode('utf-8'))
                # Use the fully-qualified schema name as the topic name
                # for the outbound stream.
                await producer.send_and_wait(
                    schema_name, value=outbound_message)

    finally:
        logger.info('Shutting down')
        consumer.stop()
        logger.info('Shutdown complete')


class SalTextTransformer:
    """A class that transforms text-formatted SAL messages to Avro.
    """

    preamble_pattern = re.compile(
        r"^(?P<topic_name>\w+):\( (?P<content>[\'\w\d\s,\.-]+)\)"
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
        items = [s.strip(" '") for s in m.group('content').split(',')]
        # The content of the message covered by the schema itself.
        data_items = items[6:]

        schema_info = await self._registry.get_schema_by_subject(
            topic_name, version='latest'
        )

        avro_data = {}

        sal_timestamp = datetime.datetime.fromtimestamp(
            float(items[2]), tz=datetime.timezone.utc)
        avro_data['kafka_timestamp'] = sal_timestamp

        scan_index = 0
        for schema_field in schema_info['schema']['fields']:
            print(schema_field)
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
    type_ = schema_field['type']
    if isinstance(type_, dict):
        if type_['type'] == 'long' and type_['type'] == 'timestamp-millis':
            return scan_timestamp_millis(schema_field, scan_index, data_items)
        elif type_['type'] == 'array':
            return scan_array(schema_field, scan_index, data_items)
        else:
            raise NotImplementedError(
                "Don't know how to scan this array field yet: "
                f"{schema_field!r}")
    elif type_ in ('float', 'double'):
        return scan_float(schema_field, scan_index, data_items)
    else:
        raise NotImplementedError(
            f"Don't know how to scan this field yet: {schema_field!r}")


def scan_float(schema_field, scan_index, data_items):
    return float(data_items[scan_index]), scan_index + 1


def scan_timestamp_millis(schema_field, scan_index, data_items):
    timestamp = float(data_items[scan_index]) / 1000.
    dt = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)
    return dt, scan_index + 1


def scan_array(schema_field, scan_index, data_items):
    count = schema_field['type']['sal_count']
    item_type = schema_field['type']['items']
    if item_type in ('float', 'double'):
        array = [float(item)
                 for item in data_items[scan_index:scan_index+count]]
    elif item_type in ('int',):
        array = [int(item)
                 for item in data_items[scan_index:scan_index+count]]
    elif item_type in ('string',):
        array = [item
                 for item in data_items[scan_index:scan_index+count]]
    else:
        raise NotImplementedError(
            f"Can't scan an array of type {schema_field!r}")

    return array, scan_index + count


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
