"""kafkaefd salschema commands for converting the `ts_sal
<https://github.com/lsst-ts/ts_xml>`_ topic schema repository into a set of
Avro schemas.
"""

__all__ = ('salschema',)

import asyncio
import json
from pathlib import Path

import aiohttp
import requests
import click

from ..salschema.repo import SalXmlRepo
from ..salschema.convert import convert_topic


@click.group()
@click.pass_context
def salschema(ctx):
    """Work with SAL schemas (converting them to Avro, for example).
    """
    session = requests.Session()
    session.headers.update({
        'Accept': 'application/vnd.schemaregistry.v1+json'
    })
    ctx.obj = {
        'session': session,
        'host': ctx.parent.obj['schema_registry_url'],
    }


@salschema.command()
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
    '--write', 'write_dir', default=None,
    type=click.Path(file_okay=False, dir_okay=True, resolve_path=True),
    help='Directory to write avro schema files to.'
)
@click.option(
    '--print', 'print_schemas', is_flag=True, default=False,
    help='Print schemas to the console'
)
@click.pass_context
def convert(ctx, xml_repo_slug, xml_repo_ref, github_username,
            github_token, write_dir, print_schemas):
    """Batch convert SAL XML schemas from the ``ts_sal`` GitHub repository to
    Avro format.

    This command obtains the source XML files directly through the GitHub API.
    To avoid API rate limits, it's a good idea to set up authenticated access
    through a personal access token, which you can create at
    https://github.com/settings/tokens. Configure your GitHub credentials
    through the ``$GITHUB_USER`` and ``$GITHUB_TOKEN`` environment variables.
    """
    xml_org, xml_repo_name = xml_repo_slug.split('/')

    async def _convert():
        async with aiohttp.ClientSession() as httpsession:
            repo = await SalXmlRepo.from_github(
                httpsession,
                github_org=xml_org,
                github_repo=xml_repo_name,
                git_ref=xml_repo_ref,
                github_user=github_username,
                github_token=github_token)

        schemas = {}
        for topic_name, topic in repo.items():
            avsc = convert_topic(topic)
            # print(json.dumps(avsc, indent=2, sort_keys=True))
            schemas[topic_name] = avsc

        if write_dir is not None:
            dirname = Path(write_dir)
            dirname.mkdir(parents=True, exist_ok=True)
            for name, schema in schemas.items():
                path = dirname / (name + '.json')
                with open(path, 'w') as f:
                    f.write(json.dumps(schema, indent=2, sort_keys=True))

        if print_schemas:
            for name, schema in schemas.items():
                print(json.dumps(schema, indent=2, sort_keys=True))

        print('Processed {0:d} schemas'.format(len(repo)))

    loop = asyncio.get_event_loop()
    loop.run_until_complete(_convert())
