# Operational Logging

The integrated monitoring runtime configures version-1 JSON logs on stderr when it owns root logging. `python -m scripts.discover` uses the same setup. Human-readable command output and discovery JSON/CSV results remain separate on stdout or the requested file.

The implementation uses Python's standard library in [logging_config.py](../../services/logging_config.py). It adds no dependencies, environment settings, file writer, exporter, or log collector.

## Format

Each record is one physical JSON line. Embedded newlines are escaped, timestamps use UTC, and the default CLI level is INFO.

| Field | Meaning |
| --- | --- |
| `schema_version` | Log envelope version, currently 1; separate from the security-event schema |
| `timestamp` | Log creation time in UTC with millisecond precision, not the original observation time |
| `level`, `logger`, `message` | Severity, producer, and bounded diagnostic summary |
| `error_type` | Optional exception class or explicitly supplied safe classification |
| `event_id`, `collector`, `network_scope`, `stage`, `operation` | Optional allowlisted scalar correlation fields; not automatically inferred on every record |
| `duration_seconds`, `count` | Optional finite, nonnegative numeric metrics within the supported bound; booleans are excluded |

Messages are limited to 4096 characters after redaction. Logger/context text is also bounded. These are character limits, not serialized-byte limits. Unknown extra fields are omitted. Logging does not persist a `SecurityEvent` or create an alert.

## Redaction and Evidence Boundaries

The formatter masks common password/token/API-key assignments, authorization/cookie headers, bearer credentials, and HTTP/PostgreSQL URLs. It also masks the configured values of `ZTE_PASSWORD`, `DISCORD_BOT_TOKEN`, `DISCORD_WEBHOOK_URL`, `TELEGRAM_BOT_TOKEN`, and `SENTINEL_DATABASE_URL`, including URL-encoded variants and a URL-form database password extracted from the DSN. Values are read at logging setup; process configuration is not modified and unrelated environment variables are not collected.

Exception arguments become class names. Exception messages, chains, tracebacks, stack dumps, and arbitrary object representations are not emitted. Dictionary/object evidence passed as a formatting argument is omitted rather than stringified. Malformed formatting produces a fixed diagnostic placeholder. Formatting does not mutate the original record, so other host handlers retain ownership of their records.

The ZTE client/collector/monitor, runtime persistence failures, notification manager, and Telegram polling report failure classifications instead of raw provider/driver messages. Monitor failure logs include stage information, and canonical-write failures include event/scope/operation context. Authentication rejection logs do not include router response text; raised exceptions retain their existing application behavior.

Redaction is defense in depth, not a classifier for every possible secret or arbitrary free text. Producers must never log raw evidence, response bodies, configuration dictionaries, or credentials. Newly introduced secret settings require explicit review of the known-value list. Runtime-only secrets supplied outside configuration still depend on producer discipline and the supported patterns. IP/MAC/hostname identities may remain operational diagnostics and require appropriate access controls.

## Host Integration and Failure Behavior

`configure_logging()` installs one handler only when root logging has no handlers. Repeated calls do not duplicate handlers or overwrite an embedding application's configuration. A host that supplies logging handlers must explicitly install `JSONLogFormatter(secrets=configured_log_secrets())` on its own outputs; those other outputs are not automatically redacted.

The CLI handler suppresses its own sink-error diagnostics so unavailable stderr does not dump the original unredacted record or interrupt monitoring. Records can be lost; there is no retry queue, durable delivery acknowledgement, or logging-health exporter. Log writes are synchronous and a blocked sink can still delay the caller. Deployment log collection, rotation, access control, disk limits, and forwarding are operational responsibilities.

Use [collector health](../architecture/security-events.md#collector-health) to distinguish poll failures from unknown presence. Use the historical repositories for evidence rather than enabling raw payload logging. Full traceback debugging requires a separately reviewed diagnostic workflow.

## Validation

[Logging tests](../../tests/test_logging_config.py) cover JSON/UTC output, newline escaping, bounded text, credential patterns and configured values, omitted exception chains/evidence, invalid inputs, unchanged records, idempotent/host-owned configuration, failed sinks, and monitoring/persistence/notification failure isolation. External services are mocked and test credentials are synthetic. See [Milestone 2 acceptance](../development/milestone-2-acceptance.md) for the full checkpoint.
