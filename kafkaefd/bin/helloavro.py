"""Hello world demo of Avro-formatted messaging.
"""

__all__ = ('helloavro',)

import click
from confluent_kafka import avro, KafkaError
from confluent_kafka.avro.serializer import SerializerError

from .utils import get_broker_url, get_registry_url


key_schema = avro.loads("""
{
  "namespace": "org.lsst.kafka_efd_demo.helloavro",
  "name": "key",
  "type": "record",
  "doc": "Schema for the helloavro Kafka message key.",
  "fields": [
    {
      "name": "name",
      "type": "string",
      "default": "default"
    }
  ]
}
""")

value_schema = avro.loads("""
{
  "namespace": "org.lsst.kafka_efd_demo.helloavro",
  "name": "value",
  "type": "record",
  "doc": "Schema for the helloavro Kafka message value.",
  "fields": [
    {
      "name": "content",
      "type": "string"
    }
  ]
}
""")


@click.group()
@click.pass_context
def helloavro(ctx):
    """Hello world demo of Avro-formatted messaging.
    """


@helloavro.command()
@click.argument('message', required=True)
@click.option(
    '--topic', default='helloavro', show_default=True,
    help='Topic identifier.'
)
@click.option(
    '--key', 'key_name', default='default', show_default=True,
    help='Key for the message.'
)
@click.pass_context
def produce(ctx, message, topic, key_name):
    """Produce an Avro-serialized message.
    """
    settings = {
        'bootstrap.servers': get_broker_url(ctx.parent),
        'schema.registry.url': get_registry_url(ctx.parent),
        'error_cb': error_cb,
        'api.version.request': True,
    }

    p = avro.AvroProducer(settings)

    key = {
        'name': key_name
    }
    value = {
        'content': message
    }
    try:
        p.produce(topic=topic, key=key, value=value,
                  key_schema=key_schema, value_schema=value_schema)
    except KeyboardInterrupt:
        pass

    if p.flush(30):
        print('Error: shutting down after flush timeout, '
              'but there are unsent messages.')


@helloavro.command()
@click.option(
    '--group', default='mygroup', show_default=True,
    help='ID of the consumer group.'
)
@click.option(
    '--client', default='client-1', show_default=True,
    help='ID of the client in the consumer group.'
)
@click.option(
    '--topic', 'topics', show_default=True,
    multiple=True, default=['helloavro'],
    help='Topic name. Provide multiple --topic options to subscribe to '
         'multiple topics.'
)
@click.pass_context
def consume(ctx, group, client, topics):
    """Consume an Avro-serialized message.
    """
    topics = [str(t) for t in topics]
    print('Starting consumer\n\tGroup: {group}\n\tClient: {client}\n\t'
          'Topic(s): {topics}'.format(
              group=group, client=client, topics=', '.join(topics)))

    settings = {
        'bootstrap.servers': get_broker_url(ctx.parent),
        'schema.registry.url': get_registry_url(ctx.parent),
        # Identify the consumer group
        'group.id': group,
        # Identify the client within the consumer group
        'client.id': client,
        # Automatically commit the current offset for this consumer
        'enable.auto.commit': True,
        'session.timeout.ms': 6000,
        'default.topic.config': {
            # "smallest" means that old messages aren't ignored if an offset
            # hasn't been committed yet. Otherwise the default is "latest",
            # which has the consumer only pick up new messages.
            'auto.offset.reset': 'smallest'
        }
    }
    c = avro.AvroConsumer(settings)
    c.subscribe(topics)

    try:
        while True:
            try:
                msg = c.poll(0.1)
            except SerializerError as e:
                print("Message deserialization failed for {}: {}".format(
                      msg, e))
                break

            if msg is None:
                continue

            elif not msg.error():
                print('Received message (topic={topic}, key={key}):'
                      '\n\t{message}'
                      .format(topic=msg.topic(), key=msg.key(),
                              message=msg.value()))

            elif msg.error().code() == KafkaError._PARTITION_EOF:
                print('End of partition reached {0}/{1}'
                      .format(msg.topic(), msg.partition()))

            else:
                print('Error occured: {0}'.format(msg.error().str()))

    except KeyboardInterrupt:
        pass

    finally:
        # Close the consumer so that the consumer group an rebalance
        c.close()


def error_cb(err):
    print('Error: %s' % err)
