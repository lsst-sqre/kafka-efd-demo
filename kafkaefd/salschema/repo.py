"""Utilities for working with the XML schema repository at
https://github.com/lsst-ts/ts_xml
"""

import asyncio
import base64
from io import BytesIO
from pathlib import Path
from collections.abc import Mapping

from aiofile import AIOFile
import cachetools
from lxml import etree
from gidgethub import aiohttp as gh_aiohttp
from gidgethub.sansio import accept_format

cache = cachetools.LRUCache(maxsize=500)


class SalXmlRepo(Mapping):
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

    @classmethod
    async def from_github(cls, httpsession, github_org='lsst-ts',
                          github_repo='ts_xml', git_ref='develop',
                          github_user=None, github_token=None,
                          cache_dir='~/.kafkaefd/github'):
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
        # Cache for files downloaded from GitHub
        cache_root = Path(cache_dir).expanduser()

        if github_user is None:
            github_user = 'kafkaefd'

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
        cache_dir = cache_root / git_sha

        if cache_dir.exists():
            # Load XML files from the cache
            topics = await SalXmlRepo._load_xml_files_from_cache(cache_dir)

        else:
            # Download XML files from GitHub API, then cache for second
            # execution
            cache_dir.mkdir(parents=True, exist_ok=True)

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
                    cls._get_blob_gh(ghclient, sem, path, url, cache_dir)
                ))
            filedata = await asyncio.gather(*tasks)

            topics = {}
            for path, data in filedata:
                topics.update(SalXmlRepo._parse_xml_topics(path, data))

            print('GitHub rate limit: {}'.format(ghclient.rate_limit))

        return cls(topics)

    @staticmethod
    async def _get_blob_gh(ghclient, sem, path, url, cache_root):
        """Asynchronously get a blob from the Git tree through the GitHub
        API.

        This method should only be called from `SalXmlRepo.from_github`.
        """
        async with sem:
            data = await ghclient.getitem(url)
            try:
                content = base64.b64decode(data['content'])
            except KeyError:
                print('keyerror')
                print(data)
                raise
        # Write to cache
        cache_path = cache_root \
            / (base64.b64encode(url.encode()).decode('utf-8') + '.xml')
        async with AIOFile(cache_path, 'wb') as f:
            await f.write(content)
            await f.fsync()
        return path, content

    @staticmethod
    async def _load_xml_files_from_cache(cache_dir):
        """Load XML files created by `_get_blob_gh`.
        """
        async def _read(path):
            async with AIOFile(path, 'rb') as f:
                filedata = await f.read()
            return path, filedata

        # Get XML file paths by walking the root cache directory
        dirs = [cache_dir]
        files = []
        while dirs:
            directory = dirs.pop()
            for path in directory.iterdir():
                if path.is_file():
                    files.append(path)
                elif path.is_dir():
                    dirs.append(path)

        # Open files asynchronously
        tasks = []
        for filepath in files:
            tasks.append(asyncio.ensure_future(
                _read(filepath)
            ))
        filedata = await asyncio.gather(*tasks)

        topics = {}
        for path, data in filedata:
            topics.update(SalXmlRepo._parse_xml_topics(path, data))

        return topics

    @staticmethod
    def _parse_xml_topics(path, xmldata):
        """Extract the ``SALCommand``, ``SALTelemetry``, and ``SALEvent``
        elements out of binary XML data.
        """
        topics = {}
        try:
            doc = etree.parse(BytesIO(xmldata))
        except etree.XMLSyntaxError as e:
            print('Error: Failed to parse {}'.format(path))
            print(e)
            return topics

        for topic_type in ('SALCommand', 'SALTelemetry', 'SALEvent'):
            for topic in doc.iterfind(topic_type):
                name = topic.find('EFDB_Topic').text
                topics[name] = topic

        return topics

    def __str__(self):
        return '<SalXmlRepo {0:d} topics>'.format(len(self))

    def __len__(self):
        return len(self._topics)

    def __getitem__(self, topic_name):
        return self._topics[topic_name]

    def __iter__(self):
        for key in self._topics:
            yield key

    def itersubsystem(self, subsystem):
        """Iterate over topics for a single SAL subsytem.
        """
        for key, topic in self.items():
            if self[key].find('Subsystem').text == subsystem:
                yield key, topic
