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
@click.pass_context
def helloproducer(ctx):
    """Hello-world producer.
    """
    settings = {
        'bootstrap.servers': get_broker_url(ctx),
    }

    p = Producer(settings)

    try:
        p.produce('mytopic', key='hello', value='world',
                  callback=producer_callback)
        # Could also do a p.poll(0.1) here to block and run the callback.
    except KeyboardInterrupt:
        pass

    if p.flush(30):
        print('Error: shutting down after flush timeout, '
              'but there are unsent messages.')


def producer_callback(err, msg):
    if err is not None:
        print("Failed to deliver message: {0}: {1}"
              .format(msg.value(), err.str()))
    else:
        print("Message produced: {0}".format(msg.value()))


@click.command()
@click.pass_context
def helloconsumer(ctx):
    """Hello-world consumer.
    """
    settings = {
        'bootstrap.servers': get_broker_url(ctx),
        # Identify the consumer group
        'group.id': 'mygroup',
        # Identify the client within the consumer group
        'client.id': 'client-1',
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
    c.subscribe(['mytopic'])

    try:
        while True:
            msg = c.poll(0.1)
            if msg is None:
                continue
            elif not msg.error():
                print('Received message: {0}:{1}'
                      .format(msg.key(), msg.value()))
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
