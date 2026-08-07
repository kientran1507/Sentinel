# Sentinel

Sentinel is a self-hosted network and infrastructure monitoring platform designed for homelab and small-scale environments. It is intended to provide centralized monitoring, device discovery, alerting, and operational visibility in a lightweight, self-managed deployment.

## Architecture

![Architecture](docs/images/architecture.svg)

The architecture overview describes the intended system boundaries, service responsibilities, and data flow for the platform.

## Documentation

- [Architecture](docs/architecture/overview.md)
- [Deployment](docs/deployment/docker.md)
- [API](docs/api/endpoints.md)
- [Monitoring](docs/monitoring/metrics.md)
- [Troubleshooting](docs/troubleshooting/common-issues.md)
- [Release Notes](docs/releases/v0.1.0.md)

## Project Status

- ✅ Foundation Complete (v0.1)
- 🚧 Device Discovery (v0.2)
- ⬜ Monitoring
- ⬜ Alerting
- ⬜ Dashboard

## Project Goals

Sentinel is designed to provide:

- Centralized infrastructure monitoring
- Device discovery and inventory awareness
- Real-time health and metric observation
- Actionable alerting and notification routing
- Lightweight deployment for constrained environments
- Extensibility for future integrations and modules
- Self-hosted architecture with operator control

## Deployment Targets

Sentinel is intended to run on:

- Docker Compose
- Kubernetes (K3s)
- Raspberry Pi
- Linux servers

## Repository Layout

```text
sentinel/
├── docs/
├── infrastructure/
├── services/
├── configs/
├── scripts/
├── tests/
├── examples/
├── diagrams/
├── .github/
├── README.md
├── CHANGELOG.md
└── LICENSE
```

## License

This project is licensed under the MIT License.

## Author

Developed as a personal infrastructure monitoring project focused on self-hosted environments, container orchestration, and modern DevOps practices.
