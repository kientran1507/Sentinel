# Sentinel

Sentinel is a self-hosted network and infrastructure monitoring platform designed for homelab and small-scale environments. It provides centralized monitoring, device discovery, health status visualization, and automated alerting to help administrators maintain reliable and secure systems.

The project aims to simplify infrastructure management by integrating multiple monitoring components into a unified platform that can be deployed on lightweight hardware such as a Raspberry Pi or on standard Linux servers.

---

## Features

* Real-time network device monitoring
* Automatic device discovery
* Health and availability monitoring
* Resource usage tracking
* Alert and notification system
* Centralized dashboard
* Docker-based deployment
* Kubernetes support
* Modular and extensible architecture
* Self-hosted and open-source

---

## Project Goals

Sentinel is designed to provide:

* Continuous monitoring of network infrastructure
* Early detection of failures and outages
* Simplified management of self-hosted services
* Lightweight deployment suitable for homelab environments
* Extensible architecture for future monitoring modules

---

## Technology Stack

The technologies used throughout the project include:

* Docker
* Kubernetes (K3s)
* Linux
* Raspberry Pi
* Python
* REST APIs
* YAML
* Git & GitHub

Additional technologies may be introduced as the project evolves.

---

## Repository Structure

```text
sentinel/
├── docs/               # Project documentation
├── infrastructure/     # Deployment and infrastructure configuration
├── monitoring/         # Monitoring components
├── scripts/            # Utility scripts
├── configs/            # Configuration files
├── assets/             # Images and diagrams
├── README.md
└── LICENSE
```

---

## Documentation

Project documentation is located in the `docs/` directory and will include:

* System Architecture
* Deployment Guide
* Installation Guide
* Configuration
* Monitoring Components
* Kubernetes Deployment
* Docker Deployment
* API Documentation
* Troubleshooting
* Future Improvements

---

## Deployment

Sentinel is designed to support deployment on:

* Raspberry Pi
* Linux Servers
* Virtual Machines
* Docker
* Kubernetes (K3s)

---

## Roadmap

* [ ] Core monitoring engine
* [ ] Device discovery
* [ ] Metrics collection
* [ ] Alert engine
* [ ] Notification service
* [ ] Web dashboard
* [ ] Authentication and user management
* [ ] REST API
* [ ] Kubernetes deployment manifests
* [ ] Comprehensive documentation

---

## Contributing

Contributions are welcome. If you have suggestions, bug reports, or feature requests, please open an issue or submit a pull request.

---

## License

This project is licensed under the MIT License.

---

## Author

Developed as a personal infrastructure monitoring project focused on self-hosted environments, container orchestration, and modern DevOps practices.
