# Sentinel Project Plan

## 1. Project Overview

**Project:** Sentinel\
**Repository:** `kientran1507/Sentinel`\
**Current stage:** v0.2 Discovery --- implementing Device Database\
**Target:** v1.0 --- Home Network SIEM & Security Monitoring Platform

Sentinel is a self-hosted security monitoring platform for a
homelab/small network. It should evolve from the current LAN discovery
and presence-monitoring system into a modular security platform capable
of:

-   Maintaining a persistent asset/device inventory
-   Collecting and normalizing security telemetry
-   Detecting suspicious behavior with deterministic rules
-   Correlating related events into incidents
-   Managing alerts and notifications
-   Providing a web dashboard and investigation interface
-   Optionally operating as an inline gateway for an isolated network
    segment
-   Integrating network IDS telemetry such as Suricata later
-   Supporting distributed sensors such as a Raspberry Pi

The project should demonstrate practical cybersecurity engineering
fundamentals rather than attempting to reproduce an enterprise SIEM.

------------------------------------------------------------------------

## 2. Current State

The current production path is a Python application containing:

-   ICMP discovery
-   ARP discovery
-   Discovery orchestration
-   Hostname enrichment
-   ZTE H3601P authenticated client/DHCP/mesh collection
-   Presence tracking
-   Device registry
-   Typed device events
-   In-process event bus
-   Rule-based alert engine
-   Alert history
-   Discord notifications
-   Telegram notifications
-   Discord/Telegram monitoring commands

Current important limitation:

> Live state is primarily held in memory. The application is still a
> modular monolith, so separate processes cannot safely share the same
> device/alert state.

The architecture should therefore be migrated incrementally rather than
immediately rewritten as many microservices.

------------------------------------------------------------------------

# 3. Architecture Principles

## 3.1 Prefer modular services, not excessive microservices

Use a small number of meaningful services:

``` text
                    SENTINEL
                       |
       +---------------+----------------+
       |               |                |
   Collectors     Event Pipeline     Control
       |               |                |
       v               v                v
 Discovery          Storage            API
 ZTE                Detection         Commands
 Syslog             Correlation
 Suricata
 Endpoint
```

Recommended eventual services:

1.  `sentinel-collector`
2.  `sentinel-event`
3.  `sentinel-detection`
4.  `sentinel-api`
5.  `sentinel-notifier`
6.  `sentinel-web`

Infrastructure:

-   PostgreSQL
-   Redis or another lightweight event transport
-   Optional Suricata
-   Optional distributed sensors

Do **not** create one service for every Python class.

------------------------------------------------------------------------

## 3.2 Persistent storage comes before process separation

The first architectural priority is to replace in-memory authoritative
state with PostgreSQL.

The following must eventually become persistent:

-   Assets
-   IP/MAC/hostname observations
-   Events
-   Alerts
-   Incidents
-   Detection rules
-   Notification history

The existing in-memory classes should first be placed behind repository
interfaces. Then PostgreSQL can replace the implementation without
changing the domain logic.

------------------------------------------------------------------------

## 3.3 Define a stable event contract

All collectors should eventually produce a common `SecurityEvent`
structure.

Example conceptual schema:

``` text
SecurityEvent
├── event_id
├── schema_version
├── timestamp
├── event_type
├── severity
├── source
├── collector
├── asset_id
├── source_ip
├── source_port
├── destination_ip
├── destination_port
├── message
└── metadata/raw_data
```

The schema must be versioned.

Collectors should not contain detection logic.

Detection services should consume normalized events.

------------------------------------------------------------------------

## 3.4 Separate detection from notification

The system must follow:

``` text
Event
  ↓
Detection
  ↓
Alert
  ↓
Notification
```

The notification service must not decide whether activity is malicious.

This allows Discord/Telegram to be replaced later without changing
security logic.

------------------------------------------------------------------------

# 4. Redesigned Milestones

The old milestones are too feature-oriented and do not represent the
architectural progression required for a SIEM.

Replace them with the following milestones.

------------------------------------------------------------------------

# Milestone 0 --- Foundation & Architecture

## Goal

Establish the repository structure, development standards, deployment
strategy, and architectural contracts.

### Tasks

-   [ ] Define architecture document
-   [ ] Define service boundaries
-   [ ] Define domain models
-   [ ] Define `SecurityEvent` schema
-   [ ] Define event type naming convention
-   [ ] Define severity levels
-   [ ] Define database migration strategy
-   [ ] Define configuration/environment strategy
-   [ ] Define logging format
-   [ ] Define testing strategy
-   [ ] Define Docker Compose development environment
-   [ ] Document threat model and trust boundaries

### Deliverable

A documented architecture that can support independent services without
requiring a complete rewrite.

------------------------------------------------------------------------

# Milestone 1 --- Asset Inventory & Device Database

## Goal

Turn discovery from a temporary scan into a persistent asset inventory.

This is the **current milestone** and should be completed before moving
into SIEM event processing.

### Core model

``` text
Asset
├── asset_id
├── MAC address
├── hostname
├── vendor
├── device_type
├── trust_level
├── first_seen
├── last_seen
├── status
└── metadata

AssetAddress
├── asset_id
├── IP address
├── interface
├── first_seen
└── last_seen
```

### Tasks

-   [ ] Design PostgreSQL schema
-   [ ] Implement database connection layer
-   [ ] Implement migrations
-   [ ] Implement `AssetRepository`
-   [ ] Implement `AssetAddressRepository`
-   [ ] Replace direct `DeviceRegistry` persistence assumptions
-   [ ] Persist discovered MAC addresses
-   [ ] Persist discovered IP addresses
-   [ ] Persist hostnames
-   [ ] Persist vendor information where available
-   [ ] Track first-seen/last-seen timestamps
-   [ ] Track device online/offline state
-   [ ] Handle IP changes without creating duplicate assets
-   [ ] Merge discovery results from ICMP and ARP
-   [ ] Merge ZTE router observations with discovery observations
-   [ ] Preserve stable asset identity
-   [ ] Add tests for asset identity and deduplication
-   [ ] Add database integration tests
-   [ ] Update `/devices` command to read from persistent storage

### Important design rule

MAC address is useful as an identity key but must not be treated as
universally immutable.

The system should support:

-   IP changing
-   hostname changing
-   device moving between interfaces
-   temporary missing observations
-   unknown devices
-   devices without MAC visibility

### Acceptance criteria

A device discovered today must still exist in the inventory after
Sentinel restarts.

An IP change must update the existing asset rather than create a
duplicate asset when sufficient identity information exists.

------------------------------------------------------------------------

# Milestone 2 --- Monitoring & Event Pipeline

## Goal

Convert monitoring observations into a persistent, normalized
security-event pipeline.

### Services

Initial target:

``` text
Collector
   ↓
Event Ingestion
   ↓
PostgreSQL
```

Later:

``` text
Collector
   ↓
Event Bus
   ↓
Event Processor
   ↓
PostgreSQL
```

### Tasks

-   [ ] Create canonical `SecurityEvent`
-   [ ] Add schema versioning
-   [ ] Define event types
-   [ ] Convert discovery events to `SecurityEvent`
-   [ ] Convert presence transitions to `SecurityEvent`
-   [ ] Convert ZTE observations to `SecurityEvent`
-   [ ] Persist events
-   [ ] Add event repository
-   [ ] Add event retention policy
-   [ ] Add structured JSON logging
-   [ ] Add event timestamps in UTC
-   [ ] Add collector/source identifiers
-   [ ] Add raw metadata field
-   [ ] Implement event validation
-   [ ] Implement event deduplication where required
-   [ ] Add event query API internally
-   [ ] Add metrics for collector health

### Initial event types

``` text
asset.discovered
asset.updated
asset.online
asset.offline
asset.recovered

network.dhcp_observation
network.hostname_observation
network.mesh_observation

collector.started
collector.stopped
collector.error
```

------------------------------------------------------------------------

# Milestone 3 --- Detection Engine

## Goal

Turn normalized events into deterministic security detections.

The detection engine should initially be rule-based. Do not introduce AI
as the primary detection mechanism.

### Detection model

``` text
SecurityEvent
      ↓
Detection Rule
      ↓
Alert
```

### Alert model

``` text
Alert
├── alert_id
├── rule_id
├── severity
├── status
├── first_seen
├── last_seen
├── event_count
├── asset_id
└── metadata
```

### Initial rules

#### ASSET-001 --- Unknown Device

Trigger when a new device appears on the monitored network.

Severity: configurable.

Possible workflow:

``` text
New MAC
  ↓
Asset not previously trusted
  ↓
Create alert
```

#### NET-001 --- Network Scan

Detect repeated connection attempts or scan telemetry when appropriate
network telemetry becomes available.

Do not claim this detection from ICMP/ARP discovery alone.

#### NET-002 --- Network Sweep

Detect a host contacting many destinations in a short time window.

Requires suitable network telemetry.

#### AUTH-001 --- Repeated Authentication Failures

Detect repeated failed authentication events from the same source.

Requires authentication log ingestion.

#### AUTH-002 --- Distributed Authentication Failures

Detect failed authentication attempts against multiple accounts or
services.

Requires authentication log ingestion.

#### NET-003 --- Restricted Network Access

Detect traffic from the room/security segment to restricted home-network
assets.

Requires Sentinel to operate as an inline gateway or otherwise receive
equivalent traffic telemetry.

### Tasks

-   [ ] Implement rule interface
-   [ ] Implement rule registry
-   [ ] Implement alert repository
-   [ ] Implement alert lifecycle
-   [ ] Implement deduplication
-   [ ] Implement thresholds/time windows
-   [ ] Implement rule configuration
-   [ ] Add detection tests
-   [ ] Add false-positive tests
-   [ ] Document every detection rule
-   [ ] Record which telemetry each rule requires

------------------------------------------------------------------------

# Milestone 4 --- Alerting & Incident Management

## Goal

Separate alerts from incidents and implement reliable notification
delivery.

### Model

``` text
Events
  ↓
Alerts
  ↓
Incident correlation
  ↓
Notifications
```

### Incident model

``` text
Incident
├── incident_id
├── title
├── severity
├── status
├── created_at
├── updated_at
├── related_assets
├── related_alerts
└── timeline
```

### Tasks

-   [ ] Implement incident repository
-   [ ] Implement alert status lifecycle
-   [ ] Implement acknowledgement
-   [ ] Implement resolution
-   [ ] Correlate related alerts
-   [ ] Build incident timeline
-   [ ] Extract notification service
-   [ ] Move Discord outbound delivery to notifier
-   [ ] Move Telegram outbound delivery to notifier
-   [ ] Add notification retry
-   [ ] Add notification delivery history
-   [ ] Prevent notification storms
-   [ ] Add severity-based notification policies

### Example correlation

``` text
Unknown device
      +
Port scan
      +
SSH failures
      +
Successful SSH login
      ↓
Single incident
```

The system should preserve all underlying events and alerts rather than
replacing them with only the incident.

------------------------------------------------------------------------

# Milestone 5 --- API & Dashboard

## Goal

Provide a web interface for investigation and system administration.

### API responsibilities

The API becomes the control boundary for:

-   Assets
-   Events
-   Alerts
-   Incidents
-   Detection rules
-   Collector status
-   System health

Discord and Telegram commands should eventually call the API rather than
access application state directly.

### Dashboard pages

#### Overview

-   Total assets
-   Online assets
-   Unknown assets
-   Open alerts
-   Open incidents
-   Collector health

#### Assets

-   Device inventory
-   IP/MAC history
-   Hostname history
-   First/last seen
-   Trust status

#### Events

-   Search
-   Filtering
-   Time range
-   Event type
-   Severity
-   Source
-   Asset

#### Alerts

-   Open alerts
-   Acknowledged alerts
-   Resolved alerts
-   Detection rule
-   Related events

#### Incidents

-   Incident summary
-   Timeline
-   Related assets
-   Related alerts
-   Investigation notes

#### System

-   Collector status
-   Event pipeline health
-   Database health
-   Notification status

### Tasks

-   [ ] Implement REST API
-   [ ] Implement authentication
-   [ ] Implement authorization
-   [ ] Implement pagination
-   [ ] Implement filtering
-   [ ] Implement dashboard frontend
-   [ ] Implement asset page
-   [ ] Implement event explorer
-   [ ] Implement alert page
-   [ ] Implement incident timeline
-   [ ] Implement system health page
-   [ ] Connect Discord/Telegram commands to API

------------------------------------------------------------------------

# Milestone 6 --- Security Gateway

## Goal

Turn Sentinel into an actual security boundary for an isolated network
segment.

This is a major architectural milestone and should happen only after the
monitoring platform is stable.

## Network architecture

``` text
                HOME NETWORK
                192.168.2.0/24
                       |
                       |
              +--------+--------+
              |     Sentinel    |
              |                 |
              | eth0            | eth1
              | HOME            | ROOM
              +--------+--------+
                       |
                       |
                ROOM NETWORK
                192.168.50.0/24
```

Sentinel becomes an L3 router/gateway.

### Requirements

-   Two physical Ethernet interfaces
-   Linux IP forwarding
-   nftables
-   DHCP service
-   DNS forwarding/resolution
-   NAT where required
-   Persistent routing configuration

### Security policy

Initial policy:

``` text
ROOM → INTERNET       ALLOW
ROOM → HOME           RESTRICT
ROOM → ROUTER         RESTRICT
ROOM → SENTINEL       REQUIRED SERVICES ONLY
HOME → ROOM           ESTABLISHED/REQUIRED ONLY
```

### Tasks

-   [ ] Add second NIC
-   [ ] Configure separate room subnet
-   [ ] Configure DHCP
-   [ ] Configure DNS forwarding
-   [ ] Enable IP forwarding
-   [ ] Implement nftables rules
-   [ ] Implement NAT
-   [ ] Test routing
-   [ ] Test firewall isolation
-   [ ] Add firewall logging
-   [ ] Convert firewall logs to SecurityEvents
-   [ ] Add restricted-network detection
-   [ ] Document trust boundaries
-   [ ] Add emergency rollback procedure

### Safety requirement

Do not put the machine inline with the production network until routing
and firewall behavior have been tested on an isolated segment.

------------------------------------------------------------------------

# Milestone 7 --- Network Telemetry & IDS

## Goal

Add actual network-security telemetry instead of relying only on
discovery.

### Recommended components

Use established security tools rather than implementing an IDS from
scratch.

Primary candidate:

-   Suricata

Optional later:

-   Zeek

### Architecture

``` text
Room Network
     ↓
Sentinel Gateway
     ↓
Traffic
     ↓
Suricata
     ↓
EVE JSON
     ↓
Sentinel Collector
     ↓
SecurityEvent
     ↓
Detection
```

### Tasks

-   [ ] Deploy Suricata
-   [ ] Configure EVE JSON
-   [ ] Create Suricata collector
-   [ ] Parse alert events
-   [ ] Parse flow events
-   [ ] Normalize Suricata events
-   [ ] Map events to assets
-   [ ] Store raw IDS metadata
-   [ ] Create IDS alert rules
-   [ ] Add IDS dashboard
-   [ ] Test with controlled traffic

### Important limitation

Sentinel only sees traffic that actually traverses the monitored
interface/gateway or is otherwise provided through a mirror/TAP.

A normal host connected to a switched/mesh LAN does not automatically
see every other host's traffic.

------------------------------------------------------------------------

# Milestone 8 --- Endpoint & Infrastructure Telemetry

## Goal

Expand Sentinel from network-only monitoring into a small multi-source
SIEM.

### Potential sources

-   Windows event logs
-   Linux journal/syslog
-   SSH authentication logs
-   Docker events
-   Docker container logs
-   Firewall logs
-   Router logs
-   Suricata
-   Raspberry Pi sensor
-   Application logs

### Tasks

-   [ ] Define log ingestion interface
-   [ ] Add Linux log collector
-   [ ] Add Windows event collector
-   [ ] Add Docker event collector
-   [ ] Add firewall log collector
-   [ ] Add router log collector where accessible
-   [ ] Normalize all sources into SecurityEvents
-   [ ] Add source health monitoring
-   [ ] Add source authentication/security

------------------------------------------------------------------------

# Milestone 9 --- Distributed Sensors

## Goal

Use Raspberry Pi and other machines as lightweight Sentinel sensors.

### Architecture

``` text
                 Sentinel Server
                       |
              Event Ingestion API
                       |
        +--------------+--------------+
        |              |              |
        v              v              v
     Pi Sensor      Gateway        Endpoint
        |              |              |
      ARP/ICMP       Traffic        Logs
      DHCP           Suricata
```

### Pi responsibilities

The Raspberry Pi should remain lightweight.

Possible functions:

-   ARP discovery
-   ICMP discovery
-   Local network observations
-   Docker monitoring
-   DHCP observations
-   Local health monitoring

The main Sentinel server remains responsible for:

-   Storage
-   Detection
-   Correlation
-   API
-   Dashboard
-   Incident management

### Tasks

-   [ ] Define sensor protocol
-   [ ] Add sensor identity
-   [ ] Add sensor authentication
-   [ ] Add event forwarding
-   [ ] Add sensor health status
-   [ ] Add disconnected-sensor detection
-   [ ] Deploy Raspberry Pi sensor
-   [ ] Document distributed deployment

------------------------------------------------------------------------

# Milestone 10 --- Investigation, Hardening & v1.0

## Goal

Make Sentinel a credible portfolio-grade security project.

### Investigation

-   [ ] Event timeline
-   [ ] Asset timeline
-   [ ] Incident timeline
-   [ ] Alert-to-event relationships
-   [ ] Event-to-asset relationships
-   [ ] Search/filtering
-   [ ] Investigation notes
-   [ ] Export incident data

### Security hardening

-   [ ] Secrets management
-   [ ] API authentication
-   [ ] API authorization
-   [ ] Least-privilege containers
-   [ ] Container filesystem hardening
-   [ ] Network segmentation
-   [ ] TLS where appropriate
-   [ ] Database access restrictions
-   [ ] Audit logging
-   [ ] Rate limiting
-   [ ] Dependency scanning
-   [ ] Container image scanning

### Reliability

-   [ ] Database backup
-   [ ] Database restore test
-   [ ] Event retention policy
-   [ ] Log rotation
-   [ ] Health checks
-   [ ] Service restart policies
-   [ ] Failure recovery tests
-   [ ] Notification retry
-   [ ] Event replay capability where practical

### Documentation

-   [ ] Architecture diagram
-   [ ] Network topology
-   [ ] Threat model
-   [ ] Detection catalog
-   [ ] Event schema
-   [ ] API documentation
-   [ ] Deployment guide
-   [ ] Troubleshooting guide
-   [ ] Security model
-   [ ] Incident response examples
-   [ ] Controlled attack/test scenarios
-   [ ] Limitations and known issues
-   [ ] Portfolio README

### v1.0 acceptance criteria

Sentinel should be able to demonstrate the following complete flow:

``` text
Telemetry
   ↓
Collection
   ↓
Normalization
   ↓
Persistent storage
   ↓
Detection
   ↓
Alert
   ↓
Correlation
   ↓
Incident
   ↓
Notification
   ↓
Dashboard investigation
```

At least one complete controlled security scenario must be reproducible
end-to-end.

------------------------------------------------------------------------

# 5. Recommended Repository Structure

Do not immediately split the repository into completely independent
repositories.

Use a monorepo:

``` text
Sentinel/
├── services/
│   ├── collector/
│   ├── event_processor/
│   ├── detection/
│   ├── api/
│   ├── notifier/
│   └── web/
│
├── sentinel_core/
│   ├── domain/
│   ├── events/
│   ├── repositories/
│   ├── config/
│   └── logging/
│
├── collectors/
│   ├── discovery/
│   ├── zte/
│   ├── syslog/
│   ├── suricata/
│   └── endpoint/
│
├── detections/
│   ├── asset/
│   ├── network/
│   ├── authentication/
│   └── rules/
│
├── database/
│   ├── migrations/
│   └── seeds/
│
├── infrastructure/
│   ├── docker/
│   ├── compose/
│   ├── firewall/
│   └── gateway/
│
├── scripts/
├── tests/
├── docs/
│   ├── architecture/
│   ├── deployment/
│   ├── detection/
│   ├── monitoring/
│   ├── security/
│   └── troubleshooting/
│
├── examples/
├── diagrams/
├── README.md
├── CHANGELOG.md
└── LICENSE
```

The exact directory names may be adapted to the existing repository.
Avoid unnecessary mass renaming during the migration.

------------------------------------------------------------------------

# 6. Migration Strategy From Current Code

Do not rewrite Sentinel from scratch.

Use this sequence:

``` text
CURRENT MONOLITH
      |
      v
1. Repository interfaces
      |
      v
2. PostgreSQL persistence
      |
      v
3. Canonical SecurityEvent
      |
      v
4. Persistent event pipeline
      |
      v
5. Extract detection process
      |
      v
6. Extract API
      |
      v
7. Extract notifier
      |
      v
8. Add dashboard
      |
      v
9. Add gateway
      |
      v
10. Add IDS
```

For each extraction, the old behavior should remain testable.

Avoid simultaneously changing:

-   database architecture
-   event schema
-   service boundaries
-   network topology
-   frontend
-   gateway configuration

in one branch.

------------------------------------------------------------------------

# 7. Database Direction

Recommended primary database:

**PostgreSQL**

Initial logical tables:

``` text
assets
asset_addresses
asset_observations

events
event_sources

detection_rules
alerts
alert_events

incidents
incident_alerts
incident_assets

notifications
notification_deliveries

sensors
```

Possible relationships:

``` text
Asset
  ├── AssetAddress
  ├── AssetObservation
  ├── Event
  ├── Alert
  └── Incident

Event
  ├── Asset
  └── Alert

Alert
  ├── Rule
  ├── Events
  └── Incident

Incident
  ├── Alerts
  └── Assets
```

Avoid premature database optimization. First establish correct data
ownership and relationships.

------------------------------------------------------------------------

# 8. Event Bus Direction

The current in-process `EventBus` should remain useful during the
migration.

Target architecture:

``` text
Collector
   ↓
Event Bus
   ↓
+-------------------+
|                   |
v                   v
Storage          Detection
                    |
                    v
                  Alert
                    |
                    v
                Notifier
```

A lightweight Redis-based transport is appropriate for the first
distributed implementation.

Do not introduce Kafka unless Sentinel's scale genuinely requires it.

------------------------------------------------------------------------

# 9. Service Responsibilities

## sentinel-collector

Responsible for collecting observations.

Allowed:

-   ICMP
-   ARP
-   DNS/hostname
-   ZTE
-   DHCP
-   Suricata
-   Syslog
-   endpoint telemetry

Not responsible for:

-   deciding whether behavior is malicious
-   sending user notifications
-   rendering dashboards

------------------------------------------------------------------------

## sentinel-event

Responsible for:

-   validating events
-   normalizing events
-   assigning event IDs
-   persistence
-   event metadata
-   deduplication
-   event retention

------------------------------------------------------------------------

## sentinel-detection

Responsible for:

-   detection rules
-   thresholds
-   correlation
-   alert creation
-   alert deduplication

Not responsible for Discord/Telegram delivery.

------------------------------------------------------------------------

## sentinel-api

Responsible for:

-   authentication
-   authorization
-   querying assets
-   querying events
-   querying alerts
-   querying incidents
-   administrative operations

------------------------------------------------------------------------

## sentinel-notifier

Responsible for:

-   Discord
-   Telegram
-   future notification channels
-   retries
-   delivery status
-   notification rate limiting

------------------------------------------------------------------------

## sentinel-web

Responsible only for presentation and user interaction.

It should consume the API rather than directly accessing PostgreSQL.

------------------------------------------------------------------------

# 10. Detection Development Standard

Every detection rule should document:

``` text
Rule ID
Name
Purpose
Severity
Required telemetry
Detection logic
Threshold
Time window
False positives
Response recommendation
Test scenario
Limitations
```

Example:

``` text
Rule: ASSET-001
Name: Unknown Device

Required telemetry:
asset.discovered

Logic:
Create an alert when a discovered asset does not have a trusted identity.

False positives:
Guest devices, IoT devices, phones, temporary devices.

Test:
Connect an unknown test device to the monitored network.

Limitations:
Discovery alone cannot prove malicious intent.
```

------------------------------------------------------------------------

# 11. Controlled Security Test Lab

Security detections should be validated against systems the user owns or
is authorized to test.

Recommended scenarios:

### Scenario A --- Unknown device

``` text
Connect test device
    ↓
Discovery
    ↓
New asset
    ↓
ASSET-001
    ↓
Alert
```

### Scenario B --- Network scan

``` text
Test VM
    ↓
Nmap scan against isolated lab network
    ↓
Network telemetry
    ↓
Detection
    ↓
Alert
```

### Scenario C --- SSH brute force

``` text
Test VM
    ↓
Repeated failed SSH logins
    ↓
Authentication logs
    ↓
AUTH-001
    ↓
Alert
```

### Scenario D --- Successful compromise simulation

``` text
Failed authentication
       +
Successful authentication
       +
Suspicious network activity
       ↓
Correlation
       ↓
Incident
```

Every simulated attack must be clearly documented as a controlled test.

------------------------------------------------------------------------

# 12. What NOT to Build Yet

Avoid spending time on these before the core pipeline works:

-   AI-based threat detection
-   LLM-generated security verdicts
-   Kubernetes deployment
-   Kafka
-   Complex distributed consensus
-   Custom IDS packet inspection
-   Custom authentication protocol
-   Multi-region architecture
-   Enterprise-scale horizontal scaling
-   Excessive microservices
-   Elaborate frontend animations

The strongest portfolio value comes from a working security pipeline
with understandable detection logic and reproducible tests.

------------------------------------------------------------------------

# 13. Portfolio Outcome

The final project should demonstrate knowledge of:

### Networking

-   ARP
-   ICMP
-   DHCP
-   DNS
-   TCP/IP
-   Routing
-   NAT
-   Network segmentation
-   Firewalling

### Security Operations

-   Asset inventory
-   Security-event collection
-   Detection engineering
-   Alert management
-   Incident correlation
-   Incident investigation
-   Security monitoring

### Security Architecture

-   Trust boundaries
-   Least privilege
-   Network segmentation
-   Gateway security
-   Defense in depth

### Software Engineering

-   Python
-   REST APIs
-   PostgreSQL
-   Event-driven architecture
-   Docker
-   Automated testing
-   Structured logging
-   Service decomposition

### Practical Security Tooling

-   Suricata
-   nftables
-   Linux networking
-   Optional Zeek
-   Endpoint/log collection

------------------------------------------------------------------------

# 14. Immediate Work Queue

The current implementation is at:

> **v0.2 --- Device Database**

Do the following next, in order:

1.  Design the PostgreSQL schema for assets.
2.  Implement database migrations.
3.  Create `AssetRepository`.
4.  Create `AssetAddressRepository`.
5.  Refactor `DeviceRegistry` to use repositories.
6.  Persist ICMP/ARP discovery results.
7.  Persist hostname enrichment.
8.  Persist ZTE observations.
9.  Implement asset deduplication.
10. Add first-seen/last-seen tracking.
11. Add database integration tests.
12. Update `/devices` to use persistent storage.
13. Document the asset identity model.
14. Close the remaining v0.2 discovery issue.
15. Start Milestone 2 only after persistence is stable.

Do **not** extract multiple processes yet.

The first architectural checkpoint is:

``` text
Discovery
    ↓
DeviceRegistry abstraction
    ↓
AssetRepository
    ↓
PostgreSQL
```

Once this works reliably, introduce `SecurityEvent`.

------------------------------------------------------------------------

# 15. Definition of v1.0

Sentinel v1.0 is complete when it is a reproducible, documented,
self-hosted security monitoring platform rather than only a network
discovery application.

Minimum v1.0 capabilities:

-   Persistent asset inventory
-   Persistent security events
-   Multiple telemetry sources
-   Rule-based detections
-   Alerts
-   Alert lifecycle
-   Incident correlation
-   Discord/Telegram notifications
-   REST API
-   Web dashboard
-   Security gateway capability for an isolated segment
-   At least one IDS integration
-   Controlled attack-test scenarios
-   Security architecture documentation
-   Automated tests
-   Backup/recovery procedure
-   Deployment documentation
-   Explicit documentation of visibility limitations

The system should prioritize correctness, observability,
maintainability, and demonstrable security concepts over feature count.

------------------------------------------------------------------------

# 16. Agent Instructions

When an AI coding agent works on Sentinel, follow these rules.

## Before modifying code

1.  Inspect the existing repository.
2.  Read the relevant architecture and development documentation.
3.  Identify the existing implementation before creating replacements.
4.  Preserve existing working functionality.
5.  Check current tests.
6.  Determine which milestone and task the requested change belongs to.

## During implementation

-   Prefer incremental refactoring.
-   Reuse existing domain logic where possible.
-   Do not create duplicate implementations.
-   Keep service boundaries explicit.
-   Keep business logic independent from Discord/Telegram.
-   Keep detection logic independent from collectors.
-   Keep the web frontend independent from the database.
-   Use typed Python models.
-   Use structured logging.
-   Add tests for changed behavior.
-   Update documentation when architecture changes.
-   Never silently remove existing functionality.

## Database changes

-   Use migrations.
-   Never depend on manually modified production schemas.
-   Preserve existing data during migrations.
-   Add indexes based on actual query patterns.
-   Use UTC timestamps.
-   Use transactions for related writes.
-   Add integration tests for repository behavior.

## Event changes

-   Never invent incompatible event fields casually.
-   Update `schema_version` when the contract changes incompatibly.
-   Preserve raw source metadata when useful.
-   Include the source/collector.
-   Make event IDs unique.
-   Make timestamps explicit.

## Security

-   Never hard-code secrets.
-   Never commit credentials.
-   Validate external input.
-   Apply least privilege.
-   Do not expose administrative APIs without authentication.
-   Treat collected network data as sensitive.
-   Use controlled environments for attack simulations.
-   Do not claim visibility that the current network topology cannot
    provide.

## Architecture changes

Before introducing a new service, answer:

1.  Why does it need to be a separate process?
2.  What data does it own?
3.  What API/event contract does it expose?
4.  What happens if it is unavailable?
5.  How is it tested independently?
6.  Does splitting it actually reduce coupling or improve deployability?

If these questions cannot be answered, keep the functionality inside the
existing service.

------------------------------------------------------------------------

# 17. Final Architecture Target

``` text
                         SENTINEL
                            |
          +-----------------+------------------+
          |                 |                  |
          v                 v                  v
      Collectors       Event Pipeline        Control
          |                 |                  |
   +------+-----+           |             +----+----+
   |      |     |           |             |         |
Discovery ZTE  Logs         v             API     Commands
   |      |     |       PostgreSQL          |
   +------+-----+           |              Web
          |                 |
          +-------> Event Bus
                            |
                    +-------+-------+
                    |               |
                    v               v
                Detection       Storage
                    |
                    v
                  Alerts
                    |
                    v
                Incidents
                    |
                    v
                Notifier
                /       \
          Discord      Telegram

Optional network path:

HOME NETWORK
192.168.2.0/24
       |
       v
Sentinel eth0
       |
Routing / nftables / Suricata
       |
Sentinel eth1
       |
ROOM NETWORK
192.168.50.0/24
```

This architecture should be treated as the long-term direction, not
something that must be implemented all at once.
