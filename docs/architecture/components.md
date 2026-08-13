# Architecture Components

This document describes the major building blocks of Sentinel and the role each one plays in the platform. Each subsystem is intended to be modular, with well-defined responsibilities and communication contracts.

## Core Subsystems

- **Discovery Service**: Detects and maintains a canonical inventory of devices on configured networks. See the device discovery design document: [Device Discovery](../monitoring/device-discovery.md).
 - **Discovery Service**: Detects and maintains a canonical inventory of devices on configured networks. The `Discovery Orchestrator` coordinates scanner implementations (ARP/ICMP) and merges results into normalized device records. See the device discovery design document: [Device Discovery](../monitoring/device-discovery.md).
- **Monitoring Service**: Schedules and executes health checks and metric collection for inventory items.
- **Alert Engine**: Evaluates telemetry and state against configured rules and emits alerts.
- **Notification Service**: Delivers alerts to external channels (email, webhook, etc.).
- **REST API**: Provides control and query endpoints for UI and external integrations.
- **Dashboard**: User-facing interface for visualization and operational workflows.
- **Database**: Stores device inventory, telemetry, alert state, and configuration metadata.

## Integration and Contracts

- Subsystems communicate through the REST API and the shared Database. The Discovery Service is the authoritative producer of device inventory; Monitoring depends on that inventory to schedule checks.
- Services should be resilient to partial failure of peers (e.g., temporary Database outage) and operate with clear retry and backoff policies.

## Discovery Service (brief)

The Discovery Service is responsible for active network scanning, device identification, and persisting normalized device records. The full design is captured in [docs/monitoring/device-discovery.md](../monitoring/device-discovery.md).
