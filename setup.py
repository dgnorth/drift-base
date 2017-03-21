from setuptools import setup, find_packages
from pip.req import parse_requirements
import pip.download

with open("VERSION") as f:
    version = f.read().strip()

setup(
    name="drift-base",
    version=version,
    license='MIT',
    author="Directive Games North",
    author_email="info@directivegames.com",
    description="Base Services for Drift.",
    packages=find_packages(
        exclude=["*.tests", "*.tests.*", "tests.*", "tests"]
    ),
    include_package_data=True,

    # the conditional on i.req avoids the error:
    # distutils.errors.DistutilsError: Could not find suitable distribution for Requirement.parse('None')
    install_requires=[
        str(i.req)
        for i in parse_requirements('requirements.txt', session=pip.download.PipSession())
        if i.req
    ],

    entry_points='''
        [drift.plugin]
        register_deployable=drift.management.commands.register:funky
        provision=drift.core.resources.postgres:provision
    ''',

    classifiers=[
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
