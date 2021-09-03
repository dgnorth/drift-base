# Drift-Base Change Log

- [Drift-Base Change Log](#drift-base-change-log)
  - [0.5.0](#050)
    - [New Features](#new-features)
    - [Bug Fixes](#bug-fixes)
    - [Deprecations](#deprecations)
  - [0.4.1](#041)
    - [Bug Fixes](#bug-fixes-1)
  - [0.4.0](#040)
    - [New Features](#new-features-1)
    - [Bug Fixes](#bug-fixes-2)
    - [Deprecations](#deprecations-1)

---
## 0.5.0

### New Features

- Add out-of-the-box support for DataDog APM tracing. Enable with ENABLE_DATADOG_APM=1. Must be used with UWSGI_LAZY_APPS=1.

### Bug Fixes

- Stabilized message exchange implementation and fixed GET for individual messages

### Deprecations

- "latest" is no longer pushed as a tag for Docker images.

---
## 0.4.1

### Bug Fixes

- Discard expired messages to avoid processing them over and over.
- Demote message logs to DEBUG.

---
## 0.4.0

### New Features

- Add party support.
- Switched to Marshmallow schemas for arguments and responses.
- Improve shutdown handling when running in a container.

### Bug Fixes

### Deprecations

- Dropped support for Python < 3.9.
- Dropped all use of `drift.schemachecker` in favor of `Flask-Marshmallow`.
