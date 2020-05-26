#!/usr/bin/env python
from setuptools import setup, find_packages

with open("VERSION") as f:
    version = f.read().strip()

setup(
    name="drift-base",
    version=version,
    license='MIT',
    author="Directive Games",
    url='https://github.com/dgnorth/drift-base',
    author_email='info@directivegames.com',
    description="Base Services for Drift.",
    packages=find_packages(
        exclude=["*.tests", "*.tests.*", "tests.*", "tests"]
    ),
    include_package_data=True,
    scripts=['scripts/static-data.py'],

    classifiers=[
        'Drift :: Tag :: Core',
        'Drift :: Tag :: Product',
        'Environment :: Web Environment',
        'Framework :: Drift',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2.7',
        'Topic :: Internet :: WWW/HTTP',
        'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
        'Topic :: Software Development :: Libraries :: Application Frameworks',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],

)
