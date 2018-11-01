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
]

tests_require = [
]

setup_requires = [
    'setuptools_scm'
]

entry_points = {}

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
    use_scm_version=True,
    setup_requires=setup_requires,
    include_package_data=True,
    entry_points=entry_points,
)
