from pathlib import Path
from setuptools import setup, find_packages

PACKAGENAME = 'kafkaefd'
DESCRIPTION = 'Demo of Kafka producers and consumers for the LSST DM EFD'
AUTHOR = 'Jonathan Sick'
AUTHOR_EMAIL = 'jsick@lsst.org'
URL = 'https://github.com/sqre-lsst/kafka-efd-demo'
LICENSE = 'MIT'
KEYWORDS = 'lsst'
CLASSIFIERS = [
    'Development Status :: 4 - Beta',
    'Programming Language :: Python :: 3.6',
    'License :: OSI Approved :: MIT License',
]

README = Path(__file__).parent / 'README.md'
with README.open() as f:
    READMETXT = f.read()

install_requires = [
    'click>=7.0,<8.0',
    'confluent-kafka[avro]==0.11.6',
    'uritemplate==3.0.0',
    'lxml==4.6.2',
    'cachetools==3.0.0',
    'aiohttp==3.4.4',
    'aiofile==1.4.3',
    'aiokafka==0.4.3',
    'gidgethub==3.0.0',
    'structlog==18.2.0',
    'prometheus-async==18.3.0',
    'prometheus-client==0.4.2',
    'kafkit==0.1.0a3',
]

tests_require = [
    # flake8 is pinned because of
    # https://github.com/tholo/pytest-flake8/issues/56
    'flake8==3.6.0',
    'pytest==3.9.3',
    'pytest-flake8==1.0.2',
    'pytest-asyncio==0.10.0',
]

extras_require = {
    'dev': tests_require
}

setup_requires = [
    'setuptools_scm',
    'pytest-runner==4.2',
]

entry_points = {
    'console_scripts': ['kafkaefd = kafkaefd.bin.main:main']
}

setup(
    name=PACKAGENAME,
    description=DESCRIPTION,
    long_description=READMETXT,
    url=URL,
    author=AUTHOR,
    author_email=AUTHOR_EMAIL,
    license=LICENSE,
    classifiers=CLASSIFIERS,
    keywords=KEYWORDS,
    packages=find_packages(exclude=['docs', 'tests*']),
    install_requires=install_requires,
    tests_require=tests_require,
    extras_require=extras_require,
    use_scm_version=True,
    setup_requires=setup_requires,
    include_package_data=True,
    entry_points=entry_points,
)
