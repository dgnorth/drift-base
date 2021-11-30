# Drift-Base Change Log

- [Drift-Base Change Log](#drift-base-change-log)
  - [0.6.0](#060)
    - [New Features](#new-features)
    - [Feature Improvements](#feature-improvements)
  - [0.5.4](#054)
    - [Bug Fixes](#bug-fixes)
    - [Optimizations](#optimizations)
  - [0.5.3](#053)
    - [Bug Fixes](#bug-fixes-1)
  - [0.5.2](#052)
    - [Optimizations](#optimizations-1)
  - [0.5.1](#051)
    - [Bug Fixes](#bug-fixes-2)
  - [0.5.0](#050)
    - [New Features](#new-features-1)
    - [Bug Fixes](#bug-fixes-3)
    - [Deprecations](#deprecations)
  - [0.4.1](#041)
    - [Bug Fixes](#bug-fixes-4)
  - [0.4.0](#040)
    - [New Features](#new-features-2)
    - [Bug Fixes](#bug-fixes-5)
    - [Deprecations](#deprecations-1)

---
## 0.6.0

### New Features

- Custom Lobbies
  * Support custom pre-match grouping of players via Lobbies and associated Gamelift match placements
- EOS support (Beta)
  * Preliminary support for authentication via Epic Online Store
  
### Feature Improvements
- Friends:
  * Friend tokens can now be generated out of wordlist in addition to uuid generation
- Flexmatch:
  * POST endpoint now accepts arbitrary extra data to be passed verbatim to Flexmatch's ticket 
  * Drift now expects backfill ticket IDs to match a regular expression defined in the tenant config 'backfill_ticket_pattern'
- Parties:
  * Players will now be removed from their party if they gracefully disconnect
  * Players can now join a party whilst being in another party, provided they flag their intention to leave the old party
  

## 0.5.4

### Optimizations

- Further improvements of player counters
- Use BigInt for counter IDs

### Bug fixes

- Fix logging of queue events
- Fix bug where notification of a potential match would only be sent to one player in a party
- Fix a bug where a player who joins a party while having a matchmaking ticket would have both marked active, potentially causing the whole party to fail to join a match.

## 0.5.3

### Bug fixes

- Fix a race issue causing wrong notification being sent to players if they managed to issue a 2nd ticket before being notified about the cancellation of the first

## 0.5.2

### Optimizations

- Optimize reporting and fetching of player counters which was unacceptably slow for any non-trivial amount of counters

## 0.5.1

### Bug fixes
- Fixing a shadowing bug in drift-flexmatch causing PotentialMatchCreated to fail on foreign tickets

## 0.5.0

### New Features

- Add out-of-the-box support for DataDog APM tracing. Enable with ENABLE_DATADOG_APM=1. Must be used with UWSGI_LAZY_APPS=1.
- Add AWS Flexmatch matchmaking support. This ofc depends on the organization having the proper AWS infrastructure in place and introduces a few new config values for the tenant:
  * **aws_gamelift_role** (no default):  The AWS role to assume when interacting with Gamelift/Flexmatch 
  * **valid_regions** (default ["eu-west-1"]): Which AWS regions are valid for matchmaking 
  * **max_rejoin_time_seconds** (default 2 minutes): How much time may pass after a ticket is completed before drift considers the ticket to be invalid for late-comers. This is mostly relevant for players in parties and those who disconnect from a match.

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