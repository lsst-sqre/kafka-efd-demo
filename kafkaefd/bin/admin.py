"""kafkaefd admin command.

Provides various administrative commands to get information from a Kafka
cluster and modify things like topics and partitions.

Adapted from
https://github.com/confluentinc/confluent-kafka-python/blob/master/examples/adminapi.py
See notice below.

Copyright 2018 Confluent Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

"""

__all__ = ('admin',)

import click
from confluent_kafka.admin import AdminClient, NewTopic, NewPartitions

from .utils import get_broker_url


@click.group()
@click.pass_context
def admin(ctx):
    """Kafka administrative commands.
    """
    settings = {
        'bootstrap.servers': get_broker_url(ctx),
    }

    client = AdminClient(settings)
    ctx.obj = {'client': client}


@admin.command()
@click.pass_context
def brokers(ctx):
    """List brokers.
    """
    client = ctx.obj['client']

    metadata = client.list_topics(timeout=10)

    print('Cluster {metadata.cluster_id} metadata (response from broker '
          '{metadata.orig_broker_name}):'.format(metadata=metadata))

    print(" {} brokers:".format(len(metadata.brokers)))
    for b in iter(metadata.brokers.values()):
        if b.id == metadata.controller_id:
            print("  {}  (controller)".format(b))
        else:
            print("  {}".format(b))


@admin.group()
@click.pass_context
def topics(ctx):
    """List and administer topics.
    """


@topics.command('list')
@click.option(
    '--all', 'list_all', is_flag=True,
    help='Show all topics, including internal Kafka topics, not just user '
         'topics. Internal topics start with an underscore'
)
@click.pass_context
def list_topics(ctx, list_all):
    """List topics.
    """
    client = ctx.parent.obj['client']

    metadata = client.list_topics(timeout=10)

    print("Listing {} topics:\n".format(len(metadata.topics)))
    topic_names = [t for t in metadata.topics.keys()]
    topic_names.sort()
    if not list_all:
        topic_names = [t for t in topic_names if not t.startswith('_')]
    for topic_name in topic_names:
        t = metadata.topics[topic_name]

        if t.error is not None:
            errstr = ": {}".format(t.error)
        else:
            errstr = ""

        if t.partitions != 1:
            fmt = '{} ({} partitions){}'
        else:
            fmt = '{} ({} partition){}'
        print(fmt.format(t, len(t.partitions), errstr))

        for p in iter(t.partitions.values()):
            if p.error is not None:
                errstr = ": {}".format(p.error)
            else:
                errstr = ""

            print("  {}\tleader: {}, replicas: {}, isrs: {}".format(
                p.id, p.leader, p.replicas, p.isrs, errstr))


@topics.command('delete')
@click.argument('topics', nargs=-1)
@click.pass_context
def delete_topics(ctx, topics):
    """Delete one or more topics.
    """
    client = ctx.parent.obj['client']

    # Call delete_topics to asynchronously delete topics, a future is returned.
    # By default this operation on the broker returns immediately while
    # topics are deleted in the background. But here we give it some time (30s)
    # to propagate in the cluster before returning.
    #
    # Returns a dict of <topic,future>.
    fs = client.delete_topics(list(topics), operation_timeout=30)

    # Wait for operation to finish.
    for topic, f in fs.items():
        try:
            f.result()  # The result itself is None
            print("Topic {} deleted".format(topic))
        except Exception as e:
            print("Failed to delete topic {}: {}".format(topic, e))


@topics.command('create')
@click.argument('topics', nargs=-1)
@click.option(
    '--partitions', '-p', default=1,
    help='Number of partitions.'
)
@click.option(
    '--replication-factor', '-r', default=3,
    help='Replication factor (number of brokers the topic is replicated on).'
)
@click.pass_context
def create_topics(ctx, topics, partitions, replication_factor):
    """Create topics.

    Pass the topic's name as the positional argument. Create multiple topics
    at once by passing multiple names.
    """
    client = ctx.parent.obj['client']

    new_topics = [NewTopic(topic, num_partitions=3, replication_factor=1)
                  for topic in topics]

    # Call create_topics to asynchronously create topics.
    # A dict of <topic,future> is returned.
    fs = client.create_topics(new_topics)

    # Wait for operation to finish.
    # Timeouts are preferably controlled by passing request_timeout=15.0
    # to the create_topics() call.
    # All futures will finish at the same time.
    for topic, f in fs.items():
        try:
            f.result()  # The result itself is None
            print("Topic {} created".format(topic))
        except Exception as e:
            print("Failed to create topic {}: {}".format(topic, e))


@topics.command('partition')
@click.argument('topic')
@click.argument('count', type=int)
@click.option('-n', 'dry_run', is_flag=True, help='Dry run')
@click.pass_context
def partition_topic(ctx, topic, count, dry_run):
    """Increase the number of partitions for a topic.
    """
    client = ctx.parent.obj['client']

    new_partitions = [NewPartitions(topic, count)]

    # Try switching validate_only to True to only validate the operation
    # on the broker but not actually perform it.
    fs = client.create_partitions(new_partitions, validate_only=dry_run)

    # Wait for operation to finish.
    for topic, f in fs.items():
        try:
            f.result()  # The result itself is None
            if dry_run:
                print('Validated additional partitions for {}'.format(topic))
            else:
                print("Additional partitions created for topic {}"
                      .format(topic))
        except Exception as e:
            print("Failed to add partitions to topic {}: {}".format(topic, e))
