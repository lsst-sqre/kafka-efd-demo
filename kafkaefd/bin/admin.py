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

import json
import re

import click
from confluent_kafka.admin import (
    AdminClient, NewTopic, NewPartitions, ConfigResource, RESOURCE_TOPIC,
    ConfigSource)

from .utils import get_broker_url

"""Map of ConfigSource ints to label strings.

AdminClient.describe_configs returns source data as an int. This mapping
is between those ints and labels that match ConfigSource attributes.
"""
CONFIG_SOURCES = {
    getattr(ConfigSource, a).value: a
    for a in ('DEFAULT_CONFIG', 'DYNAMIC_BROKER_CONFIG',
              'DYNAMIC_DEFAULT_BROKER_CONFIG', 'DYNAMIC_TOPIC_CONFIG',
              'STATIC_BROKER_CONFIG', 'UNKNOWN_CONFIG')}


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
@click.option(
    '--filter', '-f', 'filter_regex',
    help='Regex for selecting topics.'
)
@click.pass_context
def list_topics(ctx, list_all, filter_regex):
    """List topics.
    """
    client = ctx.parent.obj['client']

    metadata = client.list_topics(timeout=10)

    print("Listing {} topics:\n".format(len(metadata.topics)))
    topic_names = [t for t in metadata.topics.keys()]
    topic_names.sort()
    if not list_all:
        topic_names = [t for t in topic_names if not t.startswith('_')]
    if filter_regex:
        pattern = re.compile(filter_regex)
        topic_names = [t for t in topic_names if pattern.match(t)]

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


@topics.command('config')
@click.argument('topic')
@click.option('--set', 'settings', multiple=True, type=click.Tuple([str, str]))
@click.option('--detail', 'show_details', is_flag=True)
@click.pass_context
def configure_topic(ctx, topic, settings, show_details):
    """Show and optionally change configurations for a topic
    """
    client = ctx.parent.obj['client']

    resource = ConfigResource(RESOURCE_TOPIC, topic)

    if settings:
        # Get the initial set of configurations. The alter_configs method
        # works atomically so all of the existing and new configurations need
        # to be passed, otherwise unset configurations get reverted to
        # defaults.
        fs = client.describe_configs([resource])
        configs = fs[resource].result()  # raises on failure
        configs = {k: c.value for k, c in configs.items()}

        # Override new configurations
        configs.update(dict(settings))

        # Convert strings to their native types. describe_configs() provides
        # all configuration values as str, but alter_configs wants values to
        # be the actual types (int, float, bool, str). What can you do, eh?
        convert_configs_to_native_types(configs)

        # Apply the entire configuration set to the source
        for key, value in configs.items():
            resource.set_config(key, value)

        # Alter the configurations on the server
        fs = client.alter_configs([resource])
        fs[resource].result()  # raises on failure

    # Read configurations
    fs = client.describe_configs([resource])
    configs = fs[resource].result()  # raises on failure

    if show_details:
        # Show detailed information about each ConfigEntry
        attrs = ('value', 'is_read_only', 'is_default',
                 'is_sensitive', 'is_synonym')
        config_data = {}
        for k, config in configs.items():
            config_data[k] = {a: getattr(config, a) for a in attrs
                              if hasattr(config, a)}
            # source and synonyms need some type transforms to be useful
            try:
                config_data[k]['source'] = CONFIG_SOURCES[config.source]
            except KeyError:
                pass
            try:
                config_data[k]['synonyms'] = [k for k, _
                                              in config.synonyms.items()]
            except AttributeError:
                pass
        print(json.dumps(config_data, sort_keys=True, indent=2))

    else:
        # Just show the values of each ConfigEntry
        config_values = {k: config.value for k, config in configs.items()}
        print(json.dumps(config_values, sort_keys=True, indent=2))


def convert_configs_to_native_types(configs):
    """Convert a mapping so that values take native types, rather than
    string representations.

    Parameters
    ----------
    configs : `dict`
        Mapping of keys and values. Values are modified in place.
    """
    INT_PATTERN = re.compile(r'^[+-]?[0-9]*$')
    FLOAT_PATTERN = re.compile(r'^[+-]?([0-9]*[.])?[0-9]+$')
    TRUE_PATTERN = re.compile(r'^true$')
    FALSE_PATTERN = re.compile(r'^false$')

    for k, v in configs.items():
        if not isinstance(v, str):
            continue
        elif v == '':
            continue
        elif INT_PATTERN.match(v):
            configs[k] = int(v)
        elif FLOAT_PATTERN.match(v):
            configs[k] = float(v)
        elif TRUE_PATTERN.match(v):
            configs[k] = True
        elif FALSE_PATTERN.match(v):
            configs[k] = False
        else:
            continue
