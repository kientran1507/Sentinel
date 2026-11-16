# Development Guidance

Sentinel is a self-hosted network-monitoring project. Development primarily uses Windows; the deployment target is a Raspberry Pi 5 running Debian 12. Docker/Portainer and eventual K3s deployment are targets, not evidence of working production manifests.

## Conventions

- Read the affected implementation, tests, and architecture guides before editing.
- Keep services modular and dependencies limited to demonstrated needs.
- Prefer incremental refactoring to rewrites or premature process separation.
- Preserve discovery, presence debouncing, alerting, and command behavior.
- Keep business logic independent of Discord/Telegram and SQL out of collectors.
- Update documentation with tested changes; distinguish targets from runtime behavior.
- Use Docker Compose for local services where appropriate. Put Docker files in `infrastructure/docker` and Kubernetes files in `infrastructure/kubernetes`.
- Never expose or commit credentials, `.env`, or collected inventory databases.

Follow [contributing](CONTRIBUTING.md) for validation and the [project plan](Sentinel_Project_Plan.md) for milestone order.
