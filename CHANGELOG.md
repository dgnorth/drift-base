# Drift-Base Change Log

- [Drift-Base Change Log](#drift-base-change-log)
  - [0.12.0](#0120)
  - [0.11.0](#0110)
  - [0.10.0](#0100)
  - [0.9.0](#090)
  - [0.8.0](#080)
  - [0.7.0](#070)
  - [0.6.3](#063)
  - [0.6.2](#062)
  - [0.6.1](#061)
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
## 0.12.0

### Feature Improvements
- Give each player a global UUID as well as a player_id and put that in the JWT payload


## 0.11.0

### Bug Fixes / Feature Improvements
- Move from uwsgi to gunicorn
- Update to redis 7
- Update to postgres 15
- Update drift to 0.13
- Allow lookups of eos, gamecenter and ethereum player identities
- Authenticated player accounts now get a 'player' role by default


## 0.10.0

### Bug Fixes / Feature Improvements
- Update to Drift 0.10.2
- Improve auth handling 
- Parties/flexmatch: party ticket is now cancelled if player leaves party while searching for match
- Fix potential deadlock in match svc by introducing timeouts on held locks


## 0.9.0

### Bug Fixes / Feature Improvements
- Update to Drift 0.9.2
- Match placements now includes player latencies when starting placements
- Total match time is now correctly logged
- The Players resource now includes total play time in response if asked to
- Flexmatch tickets in state PLACING will now timeout after PLACEMENT_TIMEOUT seconds so players don't get stuck past the timeout if server doesn't comply
- Support 'system' messages/notifications coming in from other deployables
- Player latencies are now also sent as part of the players attributes in Flexmatch tickets
- Fix a bug where a players latency to a region that has been removed from valid regions would still be passed on to flexmatch
- If a player leaves a match early his ticket is now set to MATCH_COMPLETE


## 0.8.0

### New features
- Support generic match_placements without lobbies.

### Bug Fixes / Feature Improvements
- Support fetching recent matches for a given player

## 0.7.0

### New features
- New auth provider 'ethereum' added

### Bug Fixes / Feature Improvements
- Support gzipped payloads in events endpoint
- Added 'flexmatch_regions' endpoint in drift-flexmatch to expose supported regions


## 0.6.3

- Dependency updates, python-drift updated to 0.9.0

### New Features
- Datadog Runtime Metrics can now be enabled via an environment variable

### Bug Fixes / Feature Improvements
- The matches endpoint now has a PATCH handler to update a match players stats from battleservers
- drift-flexmatch will now cancel any matchmaking tickets owned by players when their client entry is removed


## 0.6.2

### Bug Fixes / Feature Improvements
- Added 'template_player_gamestate' to the players endpoint

## 0.6.1

### Bug Fixes / Feature Improvements

- drift-flexmatch now cancels a players personal matchmaking ticket if he joins a party while searching
- drift-flexmatch added a new state CANCELLING on tickets, which is active from the time a cancellation request is issued and until cancellation is confirmed by AWS. 
- drift-flexmatch will now expire COMPLETED and MATCH_COMPLETE tickets from the cache after MAX_REJOIN_TIME has passed

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

