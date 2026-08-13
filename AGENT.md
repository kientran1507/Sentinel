# AGENTS.md

## Project

Sentinel is a self-hosted network and infrastructure monitoring platform.

## Development Environment

Primary Development Machine:
- Windows PC

Primary Deployment Target:
- Raspberry Pi 5

Repository Location (Pi):
~/Desktop/Sentinel

Operating System:
Debian 12 (Bookworm)

Container Runtime:
Docker

Container Management:
Portainer

Existing Docker Stack Directory:
/opt/stacks/

Deployment Target:
K3s

Networking:
Traefik Ingress
Home Assistant
Mosquitto
Zigbee2MQTT
ESPHome
Node-RED
NetAlertX

## Development Rules

- Do not introduce unnecessary dependencies.
- Prefer Docker Compose for local development.
- Kubernetes manifests belong in `infrastructure/kubernetes`.
- Docker Compose files belong in `infrastructure/docker`.
- Keep services modular.
- Update documentation alongside code changes.
- Follow the project architecture documented in `docs/architecture`.