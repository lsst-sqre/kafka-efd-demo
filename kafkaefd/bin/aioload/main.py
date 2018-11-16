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
import requests
from uritemplate import URITemplate

from ..utils import get_registry_url
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
@click.pass_context
def upload_schemas(ctx, root_name, count):
    """Synchronize Avro schemas to the registry.
    """
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
            print("Uploaded {0} schema ID: {1:d}".format(
                subject, data['id']))


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
