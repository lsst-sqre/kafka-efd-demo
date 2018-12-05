"""kafkaefd registry command for administering the Confluent Schema Registry
for Avro schemas.
"""

__all__ = ('registry',)

import json
import re

import click
import requests
from uritemplate import expand as uriexpand


@click.group()
@click.pass_context
def registry(ctx):
    """Administer the Avro schema registry.
    """
    session = requests.Session()
    session.headers.update({
        'Accept': 'application/vnd.schemaregistry.v1+json'
    })
    ctx.obj = {
        'session': session,
        'host': ctx.parent.obj['schema_registry_url'],
    }


@registry.command('list')
@click.option(
    '--version', '-v', 'show_versions', is_flag=True,
    help='Show version IDs for each subject'
)
@click.option(
    '--compatibility', '-c', 'show_compatibility', is_flag=True,
    help='Show the compatibility configuration for each subject.'
)
@click.option(
    '--filter', '-f', 'filter_regex',
    help='Regex for selecting subjects.'
)
@click.pass_context
def list_subjects(ctx, show_versions, show_compatibility, filter_regex):
    """List subjects.
    """
    host = ctx.obj['host']
    session = ctx.obj['session']

    uri = host + '/subjects'
    r = session.get(uri)
    r.raise_for_status()
    subjects = r.json()
    subjects.sort()

    if filter_regex:
        pattern = re.compile(filter_regex)
        subjects = [s for s in subjects if pattern.match(s)]

    print('Found {0:d} subjects'.format(len(subjects)))
    for subject in subjects:
        print('  ' + subject)
        if show_versions:
            versions = _get_subject_versions(host, session, subject)
            print('    versions: {}'.format(
                ', '.join([str(v) for v in versions])))
        if show_compatibility:
            compatibility = _get_subject_compatibility(host, session, subject)
            print('    compatibility: {}'.format(compatibility))

    if show_compatibility:
        compatibility = _get_global_compatibility(host, session)
        print('\nDefault compatibility: {}'.format(compatibility))


@registry.command('show')
@click.argument('subject', type=str)
@click.option(
    '--version', '-v', default='latest', show_default=True, type=str,
    help='Subject version ID. Default is to automatically find the latest '
         'version.')
@click.pass_context
def show_schema(ctx, subject, version):
    """Show the schema for a subject.

    By default this command shows the *latest* version of a subject's schema,
    but a particular version ID can be set with the --version/-v option.
    """
    host = ctx.obj['host']
    session = ctx.obj['session']

    uri = host + '/subjects{/subject}/versions{/version}'
    uri = uriexpand(uri, subject=subject, version=version)
    r = session.get(uri)
    r.raise_for_status()
    data = r.json()

    actual_version = data['version']
    schema = json.loads(data['schema'])

    print(f'{subject} version {actual_version:d}:\n')
    print(json.dumps(schema, sort_keys=True, indent=2))


@registry.command('test')
@click.argument('subject')
@click.argument(
    'schema', type=click.File(mode='r'),
)
@click.option(
    '--version', '-v', default='latest', show_default=True, type=str,
    help='Subject version ID to test against. Default is to automatically '
         'find the latest version.'
)
@click.pass_context
def test_compatibility(ctx, subject, schema, version):
    """Test the compatibility of a schema with an existing version of a
    subject.
    """
    host = ctx.obj['host']
    session = ctx.obj['session']

    schemadata = schema.read()  # click automatically closes the file

    requestdata = {'schema': schemadata}

    uri = host + '/compatibility/subjects{/subject}/versions{/version}'
    uri = uriexpand(uri, subject=subject, version=version)
    r = session.post(uri, json=requestdata)
    r.raise_for_status()
    data = r.json()
    print('Compatible: {}'.format(data['is_compatible']))


@registry.command('upload')
@click.argument('subject')
@click.argument(
    'schema', type=click.File(mode='r'),
)
@click.pass_context
def upload_schema(ctx, subject, schema):
    """Upload a new version of a subject.

    The subject is created by the command if necessary.
    """
    host = ctx.obj['host']
    session = ctx.obj['session']

    schemadata = schema.read()  # click automatically closes the file
    requestdata = {'schema': schemadata}

    uri = host + '/subjects{/subject}/versions'
    uri = uriexpand(uri, subject=subject)
    r = session.post(uri, json=requestdata)
    r.raise_for_status()
    data = r.json()
    print("Uploaded schema ID: {0:d}".format(data['id']))


@registry.command('delete')
@click.argument('subject')
@click.option(
    '--version', '-v', type=str, multiple=True,
    help='Version ID to delete. If set, the subject itself is not deleted.'
)
@click.pass_context
def delete_subject(ctx, subject, version):
    """Delete a subject, or specific versions of a subject.

    To delete a subject::

        kafkaefd registry delete subjectname

    To delete version ``1`` of ``subjectname``::

        kafkaefd registry delete subjectname -v 1
    """
    host = ctx.obj['host']
    session = ctx.obj['session']

    # Cast versions to strings
    versions = [str(v) for v in version]
    if versions:
        for version in versions:
            _delete_version(host, session, subject, version)
            print('Deleted version {0}'.format(version))
    else:
        _delete_subject(host, session, subject)
        print('Deleted subject {}'.format(subject))


@registry.command('compat')
@click.option(
    '--subject',
    help='View or update compatibility for this subject only.'
)
@click.option(
    '--set', 'setting',
    type=click.Choice(['NONE', 'FULL', 'FORWARD', 'BACKWARD']),
    help='Set the global or subject-specific compatibility level.'
)
@click.pass_context
def show_and_edit_compatibility(ctx, subject, setting):
    """View the global or subject-specific compatibility configuration and
    optionally change that configuration.
    """
    host = ctx.obj['host']
    session = ctx.obj['session']

    if subject:
        if setting:
            _set_subject_compatibility(host, session, subject, setting)
        c = _get_subject_compatibility(host, session, subject)
        print('{} compatibility: {}'.format(subject, c))
    else:
        if setting:
            _set_global_compatibility(host, session, subject, setting)

        c = _get_global_compatibility(host, session, setting)
        print('Global compatibility: {}'.format(c))


def _get_subject_versions(host, session, subject):
    uri = host + '/subjects{/subject}/versions'
    uri = uriexpand(uri, subject=subject)
    r = session.get(uri)
    r.raise_for_status()
    versions = r.json()
    return versions


def _get_subject_compatibility(host, session, subject):
    uri = host + '/config{/subject}'
    uri = uriexpand(uri, subject=subject)
    r = session.get(uri)
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            return 'default'
        else:
            raise
    # 'compatibility' is the key in the docs, but apparently it changed
    return r.json()['compatibilityLevel']


def _set_subject_compatibility(host, session, subject, level):
    uri = host + '/config{/subject}'
    uri = uriexpand(uri, subject=subject)
    r = session.put(uri, json={'compatibility': level})
    r.raise_for_status()


def _get_global_compatibility(host, session):
    uri = host + '/config'
    r = session.get(uri)
    r.raise_for_status()
    # 'compatibility' is the key in the docs, but apparently it changed
    return r.json()['compatibilityLevel']


def _set_global_compatibility(host, session, level):
    uri = host + '/config'
    r = session.put(uri, json={'compatibility': level})
    r.raise_for_status()


def _delete_version(host, session, subject, version):
    uri = host + '/subjects{/subject}/versions{/version}'
    uri = uriexpand(uri, subject=subject, version=version)
    r = session.delete(uri)
    r.raise_for_status()
    return r.json()


def _delete_subject(host, session, subject):
    uri = host + '/subjects{/subject}'
    uri = uriexpand(uri, subject=subject)
    r = session.delete(uri)
    r.raise_for_status()
    return r.json()
