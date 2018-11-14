"""Implementation of the kafkaefd aioload commands for testing latency
in Kafka production and consumption under different loads (topic volume and
frequency).
"""

__all__ = ('aioload',)

import datetime
from io import BytesIO
import json
from pathlib import Path

import click
import fastavro

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
        create_indexed_schema('simple-value', index=0))

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
