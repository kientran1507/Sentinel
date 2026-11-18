"""Versioned storage schema migrations shared by supported backends."""
from __future__ import annotations

from dataclasses import dataclass

from .base import StorageInitializationError


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]


ADDRESS_HISTORY_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS asset_address_assignments (
        assignment_id TEXT PRIMARY KEY, asset_id TEXT NOT NULL,
        network_scope TEXT NOT NULL, ip_address TEXT NOT NULL, interface TEXT, source TEXT,
        first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
        assignment_started TEXT NOT NULL, assignment_ended TEXT,
        metadata TEXT NOT NULL DEFAULT '{}',
        FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_address_assignments_active ON asset_address_assignments (network_scope, ip_address) WHERE assignment_ended IS NULL",
    "CREATE INDEX IF NOT EXISTS idx_address_assignments_asset_time ON asset_address_assignments (asset_id, assignment_started)",
    """INSERT INTO asset_address_assignments (
        assignment_id, asset_id, network_scope, ip_address, interface, source,
        first_seen, last_seen, assignment_started, assignment_ended, metadata
    ) SELECT 'legacy:' || asset_id || ':' || ROW_NUMBER() OVER (
        PARTITION BY asset_id ORDER BY network_scope, ip_address
    ), asset_id, network_scope, ip_address, interface, source,
        first_seen, last_seen, COALESCE(assignment_started, first_seen), assignment_ended, metadata
    FROM asset_addresses""",
)


SECURITY_EVENT_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS security_events (
        event_id TEXT NOT NULL PRIMARY KEY, schema_version INTEGER NOT NULL CHECK (schema_version = 1),
        timestamp TEXT NOT NULL, event_type TEXT NOT NULL, severity TEXT NOT NULL,
        source TEXT NOT NULL, collector TEXT, asset_id TEXT, network_scope TEXT NOT NULL,
        payload TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_security_events_time ON security_events (timestamp, event_id)",
    "CREATE INDEX IF NOT EXISTS idx_security_events_scope_time ON security_events (network_scope, timestamp, event_id)",
    "CREATE INDEX IF NOT EXISTS idx_security_events_asset_time ON security_events (asset_id, timestamp, event_id)",
    "CREATE INDEX IF NOT EXISTS idx_security_events_type_time ON security_events (event_type, timestamp, event_id)",
    "CREATE INDEX IF NOT EXISTS idx_security_events_source_time ON security_events (source, timestamp, event_id)",
)


DETECTION_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS detection_findings (
        finding_id TEXT PRIMARY KEY, rule_id TEXT NOT NULL, network_scope TEXT NOT NULL,
        asset_id TEXT, last_seen TEXT NOT NULL, payload TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')), resolved_at TEXT,
        CHECK ((status = 'open' AND resolved_at IS NULL) OR (status = 'resolved' AND resolved_at IS NOT NULL))
    )""",
    """CREATE TABLE IF NOT EXISTS detection_evidence (
        finding_id TEXT NOT NULL, event_id TEXT NOT NULL,
        PRIMARY KEY (finding_id, event_id),
        FOREIGN KEY (finding_id) REFERENCES detection_findings(finding_id) ON DELETE CASCADE
    )""",
    "CREATE INDEX IF NOT EXISTS idx_detections_scope_time ON detection_findings (network_scope, last_seen, finding_id)",
    "CREATE INDEX IF NOT EXISTS idx_detections_asset_time ON detection_findings (asset_id, last_seen, finding_id)",
    "CREATE INDEX IF NOT EXISTS idx_detections_rule_time ON detection_findings (rule_id, last_seen, finding_id)",
    "CREATE INDEX IF NOT EXISTS idx_detections_status_time ON detection_findings (status, last_seen, finding_id)",
    "CREATE INDEX IF NOT EXISTS idx_detection_evidence_event ON detection_evidence (event_id, finding_id)",
)


DETECTION_AUDIT_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS detection_resolutions (
        finding_id TEXT PRIMARY KEY,
        actor_platform TEXT NOT NULL CHECK (actor_platform IN ('discord', 'telegram')),
        actor_id TEXT NOT NULL, reason TEXT NOT NULL, resolved_at TEXT NOT NULL,
        FOREIGN KEY (finding_id) REFERENCES detection_findings(finding_id) ON DELETE CASCADE
    )""",
)


DETECTION_ACKNOWLEDGEMENT_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS detection_acknowledgements (
        finding_id TEXT PRIMARY KEY,
        actor_platform TEXT NOT NULL CHECK (actor_platform IN ('discord', 'telegram')),
        actor_id TEXT NOT NULL, reason TEXT NOT NULL, acknowledged_at TEXT NOT NULL,
        FOREIGN KEY (finding_id) REFERENCES detection_findings(finding_id) ON DELETE CASCADE
    )""",
)


INCIDENT_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS incidents (
        incident_id TEXT PRIMARY KEY, network_scope TEXT NOT NULL, case_key TEXT NOT NULL,
        title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('open', 'resolved')), resolved_at TEXT,
        UNIQUE (network_scope, case_key),
        CHECK ((status='open' AND resolved_at IS NULL) OR (status='resolved' AND resolved_at IS NOT NULL))
    )""",
    """CREATE TABLE IF NOT EXISTS incident_events (
        event_id TEXT PRIMARY KEY, incident_id TEXT NOT NULL,
        timestamp TEXT NOT NULL, event_type TEXT NOT NULL, payload TEXT NOT NULL,
        FOREIGN KEY (incident_id) REFERENCES incidents(incident_id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS incident_findings (
        incident_id TEXT NOT NULL, finding_id TEXT NOT NULL, event_id TEXT NOT NULL UNIQUE,
        PRIMARY KEY (incident_id, finding_id),
        FOREIGN KEY (incident_id) REFERENCES incidents(incident_id) ON DELETE CASCADE,
        FOREIGN KEY (event_id) REFERENCES incident_events(event_id) ON DELETE CASCADE
    )""",
    "CREATE INDEX IF NOT EXISTS idx_incidents_scope_time ON incidents (network_scope, created_at, incident_id)",
    "CREATE INDEX IF NOT EXISTS idx_incident_events_time ON incident_events (incident_id, timestamp, event_id)",
    "CREATE INDEX IF NOT EXISTS idx_incident_findings_finding ON incident_findings (finding_id, incident_id)",
)


DELIVERY_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS notification_deliveries (
        attempt_id TEXT PRIMARY KEY, network_scope TEXT NOT NULL, alert_id TEXT NOT NULL,
        provider TEXT NOT NULL, started_at TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('started', 'succeeded', 'failed')),
        finished_at TEXT, error_category TEXT,
        CHECK ((status='started' AND finished_at IS NULL AND error_category IS NULL)
            OR (status='succeeded' AND finished_at IS NOT NULL AND error_category IS NULL)
            OR (status='failed' AND finished_at IS NOT NULL AND error_category='provider-error' AND error_category IS NOT NULL))
    )""",
    "CREATE INDEX IF NOT EXISTS idx_deliveries_scope_time ON notification_deliveries (network_scope, started_at, attempt_id)",
    "CREATE INDEX IF NOT EXISTS idx_deliveries_alert_time ON notification_deliveries (network_scope, alert_id, started_at, attempt_id)",
    "CREATE INDEX IF NOT EXISTS idx_deliveries_status_time ON notification_deliveries (network_scope, status, started_at, attempt_id)",
)


OUTBOX_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS notification_outbox (
        job_id TEXT PRIMARY KEY, network_scope TEXT NOT NULL, destination TEXT NOT NULL,
        provider TEXT NOT NULL, alert_id TEXT NOT NULL, snapshot TEXT NOT NULL, policy TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('queued', 'in_flight', 'retry_wait', 'sent', 'failed', 'uncertain')),
        attempt_count INTEGER NOT NULL CHECK (attempt_count BETWEEN 0 AND 3),
        next_attempt_at TEXT, active_attempt_id TEXT, lease_expires_at TEXT,
        UNIQUE (network_scope, destination, alert_id),
        FOREIGN KEY (active_attempt_id) REFERENCES notification_deliveries(attempt_id)
    )""",
    """CREATE TABLE IF NOT EXISTS notification_outbox_attempts (
        job_id TEXT NOT NULL, attempt_no INTEGER NOT NULL CHECK (attempt_no BETWEEN 1 AND 3),
        attempt_id TEXT PRIMARY KEY, outcome TEXT CHECK (outcome IN ('sent', 'retry', 'rejected', 'uncertain')),
        UNIQUE (job_id, attempt_no),
        FOREIGN KEY (job_id) REFERENCES notification_outbox(job_id) ON DELETE CASCADE,
        FOREIGN KEY (attempt_id) REFERENCES notification_deliveries(attempt_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_outbox_due ON notification_outbox (network_scope, status, next_attempt_at, job_id)",
    "CREATE INDEX IF NOT EXISTS idx_outbox_expiry ON notification_outbox (network_scope, status, lease_expires_at, job_id)",
)


MIGRATIONS = (
    Migration(
        1,
        "persistent inventory foundation",
        (
            """CREATE TABLE IF NOT EXISTS storage_metadata (
                id INTEGER PRIMARY KEY CHECK (id = 1), schema_version INTEGER NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS devices (
                identity_key TEXT PRIMARY KEY, mac_address TEXT UNIQUE, ip_address TEXT,
                hostname TEXT, discovery_source TEXT NOT NULL, first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL, status TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}'
            )""",
            """CREATE TABLE IF NOT EXISTS assets (
                asset_id TEXT PRIMARY KEY, mac_address TEXT UNIQUE, hostname TEXT, vendor TEXT,
                device_type TEXT, trust_level TEXT NOT NULL DEFAULT 'unknown',
                status TEXT NOT NULL DEFAULT 'unknown', first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}',
                network_scope TEXT NOT NULL DEFAULT 'default',
                is_provisional INTEGER NOT NULL DEFAULT 0
            )""",
            """CREATE TABLE IF NOT EXISTS asset_addresses (
                asset_id TEXT NOT NULL, network_scope TEXT NOT NULL DEFAULT 'default',
                ip_address TEXT NOT NULL, interface TEXT, source TEXT, first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL, assignment_started TEXT, assignment_ended TEXT,
                metadata TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (asset_id, network_scope, ip_address),
                FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE
            )""",
            """CREATE TABLE IF NOT EXISTS asset_observations (
                observation_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE,
                asset_id TEXT, network_scope TEXT NOT NULL, source TEXT NOT NULL,
                observed_at TEXT NOT NULL, ingested_at TEXT NOT NULL, raw_mac_address TEXT,
                normalized_mac_address TEXT, ip_address TEXT, hostname TEXT, interface TEXT,
                parent_mac_address TEXT, connection_type TEXT, rssi REAL, wireless INTEGER,
                metadata TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE SET NULL
            )""",
            """CREATE TABLE IF NOT EXISTS device_events (
                event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, timestamp TEXT NOT NULL,
                device_identity TEXT NOT NULL, mac_address TEXT, ip_address TEXT, hostname TEXT,
                previous_state TEXT, current_state TEXT, metadata TEXT NOT NULL DEFAULT '{}',
                device_snapshot TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS alerts (
                alert_id TEXT PRIMARY KEY, alert_type TEXT NOT NULL, severity TEXT NOT NULL,
                title TEXT NOT NULL, message TEXT NOT NULL, timestamp TEXT NOT NULL,
                device_identity TEXT NOT NULL, event_id TEXT NOT NULL, event_snapshot TEXT NOT NULL
            )""",
            "CREATE INDEX IF NOT EXISTS idx_asset_addresses_lookup ON asset_addresses (network_scope, ip_address, last_seen)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_asset_addresses_active_scope_ip ON asset_addresses (network_scope, ip_address) WHERE assignment_ended IS NULL",
            "CREATE INDEX IF NOT EXISTS idx_asset_observations_asset_time ON asset_observations (asset_id, observed_at)",
            "CREATE INDEX IF NOT EXISTS idx_asset_observations_source_time ON asset_observations (source, observed_at)",
            "CREATE INDEX IF NOT EXISTS idx_device_events_timestamp ON device_events (timestamp, event_id)",
            "CREATE INDEX IF NOT EXISTS idx_device_events_identity ON device_events (device_identity, timestamp, event_id)",
            "CREATE INDEX IF NOT EXISTS idx_device_events_type ON device_events (event_type, timestamp, event_id)",
            "CREATE INDEX IF NOT EXISTS idx_alerts_timestamp ON alerts (timestamp, alert_id)",
            "CREATE INDEX IF NOT EXISTS idx_alerts_identity ON alerts (device_identity, timestamp, alert_id)",
            "CREATE INDEX IF NOT EXISTS idx_alerts_severity_type ON alerts (severity, alert_type, timestamp, alert_id)",
        ),
    ),
    Migration(2, "preserve address assignment intervals", ADDRESS_HISTORY_STATEMENTS),
    Migration(3, "canonical security events", SECURITY_EVENT_STATEMENTS),
    Migration(4, "canonical detection findings", DETECTION_STATEMENTS),
    Migration(5, "audited finding resolution", DETECTION_AUDIT_STATEMENTS),
    Migration(6, "audited finding acknowledgement", DETECTION_ACKNOWLEDGEMENT_STATEMENTS),
    Migration(7, "scoped incidents and operator timelines", INCIDENT_STATEMENTS),
    Migration(8, "notification send-attempt history", DELIVERY_STATEMENTS),
    Migration(9, "explicit bounded notification dispatch", OUTBOX_STATEMENTS),
)


def apply_migrations(connection) -> None:
    """Apply each migration in the caller's transaction, atomically."""
    connection.execute("CREATE TABLE IF NOT EXISTS storage_metadata (id INTEGER PRIMARY KEY CHECK (id = 1), schema_version INTEGER NOT NULL)")
    row = connection.execute("SELECT schema_version FROM storage_metadata WHERE id = 1").fetchone()
    current = int((row["schema_version"] if hasattr(row, "keys") else row[0]) if row else 0)
    target = MIGRATIONS[-1].version
    if current > target:
        raise StorageInitializationError(
            f"PostgreSQL schema version {current} exceeds supported version {target}. Update Sentinel before connecting."
        )
    for migration in MIGRATIONS:
        if migration.version <= current:
            continue
        for statement in migration.statements:
            connection.execute(statement)
        connection.execute("INSERT INTO storage_metadata (id, schema_version) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET schema_version = excluded.schema_version", (migration.version,))
