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
    description="Base Services for Drift micro-framework.",
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
)
