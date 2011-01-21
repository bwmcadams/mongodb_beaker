#!/usr/bin/env python
#
# Copyright (c) 2009-2011 Brendan W. McAdams <bwmcadams@evilmonkeylabs.com>
#

try:
    from setuptools import setup, find_packages
except ImportError:
    import ez_setup
    ez_setup.use_setuptools()
    from setuptools import setup, find_packages

setup(
    name = 'mongodb_beaker',
    version = '0.2',
    description = 'Beaker backend to write sessions and caches to a ' +\
    'MongoDB schemaless database.',
    long_description = '\n' + open('README').read(),
    author='Brendan W. McAdams',
    author_email = 'bwmcadams@gmail.com',
    keywords = 'mongo mongodb beaker cache session',
    license = 'New BSD License',
    url = 'http://github.com/bwmcadams/mongodb_beaker/',
    tests_require = ['nose', 'webtest'],
    test_suite='nose.collector',
    classifiers = [
        'Development Status :: 4 - Beta',
        'Environment :: Other Environment',
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Topic :: Database',
        'Topic :: Utilities',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
    packages = find_packages(),
    include_package_data=True,
    zip_safe = True,
    entry_points="""
    [beaker.backends]
    mongodb = mongodb_beaker:MongoDBNamespaceManager    
    """,
    install_requires = [
        'pymongo>=1.9',
        'beaker>=1.5'
    ]

)
