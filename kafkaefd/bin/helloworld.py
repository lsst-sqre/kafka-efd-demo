"""Hello world producer.

These producers and consumers send unicode text messages using the
confluent_kafka client package.

This is based on the introductory post from Confluent:
https://www.confluent.io/blog/introduction-to-apache-kafka-for-python-programmers/
"""

__all__ = ('helloproducer', 'helloconsumer')

import click
from confluent_kafka import Producer, Consumer, KafkaError

from .utils import get_broker_url


@click.command()
@click.argument(
    'value', default="world", required=False, nargs=1
)
@click.option(
    '--key', default='hello', show_default=True,
    help='Key for the message.'
)
@click.option(
    '--topic', default='mytopic', show_default=True,
    help='Topic identifier'
)
@click.pass_context
def helloproducer(ctx, value, key, topic):
    """Hello-world producer that produces plain text messages.
    """
    settings = {
        'bootstrap.servers': get_broker_url(ctx),
    }

    p = Producer(settings)

    try:
        p.produce(topic, key=key, value=value, callback=producer_callback)
        # Could also do a p.poll(0.1) here to block and run the callback.
    except KeyboardInterrupt:
        pass

    if p.flush(30):
        print('Error: shutting down after flush timeout, '
              'but there are unsent messages.')


def producer_callback(err, msg):
    if err is not None:
        print("Failed to deliver message:\n\tkey={0}\n\tvalue={1}\n\t{2}"
              .format(msg.key(), msg.value(), err.str()))
    else:
        print("Message produced:\n\tkey={0}\n\tvalue={1}"
              .format(msg.key(), msg.value()))


@click.command()
@click.option(
    '--group', default='mygroup', show_default=True,
    help='ID of the consumer group.'
)
@click.option(
    '--client', default='client-1', show_default=True,
    help='ID of the client in the consumer group.'
)
@click.option(
    '--topic', 'topics', default=['mytopic'], show_default=True, multiple=True,
    help='Topic name. Provide multiple --topic options to subscribe to '
         'multiple topics.'
)
@click.pass_context
def helloconsumer(ctx, group, client, topics):
    """Hello-world consumer.
    """
    topics = [str(t) for t in topics]
    print('Starting consumer\n\tGroup: {group}\n\tClient: {client}\n\t'
          'Topic(s): {topics}'.format(
              group=group, client=client, topics=', '.join(topics)))

    settings = {
        'bootstrap.servers': get_broker_url(ctx),
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

    c = Consumer(settings)
    c.subscribe(topics)

    try:
        while True:
            msg = c.poll(0.1)
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
