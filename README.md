[![Build Status](https://travis-ci.org/dgnorth/drift-base.svg?branch=master)](https://travis-ci.org/dgnorth/drift-base)
[![codecov](https://codecov.io/gh/dgnorth/drift-base/branch/master/graph/badge.svg)](https://codecov.io/gh/dgnorth/drift-base)


# drift-base
Base Services for Drift micro-framework.


## Installation:
For developer setup [pipenv](https://docs.pipenv.org/) is used to set up virtual environment and install dependencies.

```bash
pip install --user pipenv
pipenv --two
pipenv install -d -e "."
```

Note that the local server and CLI should be executed within the virtual environment. You can activate it with `pipenv shell`.

#### Errata:
In dev mode, the *drift* library will not be installed with it's proper extras due to a bug or limitation in *pipenv*. Set *drift* up in develop mode as a work-around (see below).

## Other drift libraries in develop mode
Development of the *drift* library makes most sense within the context of a project like drift-base. To set up drift in develop mode:

Make sure the **virtual environment for drift-base is active** and run the following command from the root of the *drift* project folder: `pip install -e ".[aws,dev]" `.

The same can be done for the *drift-config* library. From the root of that project folder, run this command: `pip install -e "."`


