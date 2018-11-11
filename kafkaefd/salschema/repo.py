"""Utilities for working with the XML schema repository at
https://github.com/lsst-ts/ts_xml
"""

import asyncio
import base64
from io import BytesIO

import aiohttp
import cachetools
from lxml import etree
from gidgethub import aiohttp as gh_aiohttp
from gidgethub.sansio import accept_format

cache = cachetools.LRUCache(maxsize=500)


class SalXmlRepo():
    """The ``ts_sal`` topic schema repository.

    Parameters
    ----------
    topics : `list` of ``lxml`` elements.
        Elements of SAL schema topics. The elememnts can be these tags:

        - ``SALCommand``
        - ``SALTelemetry``
        - ``SALEvent``
    """

    def __init__(self, topics):
        self._topics = topics
        print('found {} topics'.format(len(self._topics)))

    @classmethod
    async def from_github(cls, httpsession, github_org='lsst-ts',
                          github_repo='ts_xml', git_ref='develop',
                          github_user=None, github_token=None):
        """Load the ``ts_sal`` repository directly from GitHub.

        Parameters
        ----------
        httpsession : `aiohttp.ClientSession`
            Session from aiohttp.
        github_org : `str`
            Owner of the GitHub repository.
        github_repo : `str`
            Name of the repository.
        git_ref : `str`
            Branch or tag name to check out.
        github_user : `str`
            Your GitHub username, if providing a ``github_token``.
        github_token : `str`
            GitHub token (such as a personal access token).

        Returns
        -------
        repo : `SalXmlRepo`
            SAL XML repository.
        """
        ghclient = gh_aiohttp.GitHubAPI(
            httpsession,
            github_user,
            oauth_token=github_token,
            cache=cache)

        git_sha = await ghclient.getitem(
            '/repos{/owner}{/repo}/commits{/ref}',
            url_vars={
                'owner': github_org,
                'repo': github_repo,
                'ref': git_ref},
            accept=accept_format(media='sha', json=False)
        )

        data = await ghclient.getitem(
            '/repos{/owner}{/repo}/git/trees{/sha}?recursive=1',
            url_vars={
                'owner': github_org,
                'repo': github_repo,
                'sha': git_sha}
        )
        if data['truncated']:
            raise RuntimeError('/git/trees result is truncated')

        paths = []
        for blob in data['tree']:
            if blob['type'] != 'blob':
                continue

            if blob['path'].startswith('sal_interfaces/') \
                    and blob['path'].endswith('.xml'):
                paths.append((blob['path'], blob['url']))

        tasks = []
        sem = asyncio.Semaphore(10)
        for path, url in paths:
            tasks.append(asyncio.ensure_future(
                cls._get_blob_gh(ghclient, sem, path, url)
            ))

        filedata = await asyncio.gather(*tasks)
        topics = {}
        for path, data in filedata:
            try:
                doc = etree.parse(BytesIO(data))
            except etree.XMLSyntaxError as e:
                print('Error: Failed to parse {}'.format(path))
                print(e)
                continue
            for topic_type in ('SALCommand', 'SALTelemetry', 'SALEvent'):
                for topic in doc.iterfind(topic_type):
                    name = topic.find('EFDB_Topic').text
                    topics[name] = topic

        print('GitHub rate limit: {}'.format(ghclient.rate_limit))

        return cls(topics)

    @staticmethod
    async def _get_blob_gh(ghclient, sem, path, url):
        """Asynchronously get a blob from the Git tree through the GitHub
        API.

        This method should only be called from `GitHubSalXmlRepo.load`.
        """
        async with sem:
            data = await ghclient.getitem(url)
            try:
                content = base64.b64decode(data['content'])
            except KeyError:
                print('keyerror')
                print(data)
                raise
        return path, content
