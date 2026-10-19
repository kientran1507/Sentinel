# Raspberry Pi

Raspberry Pi 5 on Debian 12 is the documented deployment target, not a certified packaged deployment. The recorded checkout location is `~/Desktop/Sentinel`; existing stack management uses Docker/Portainer under `/opt/stacks/`. No Sentinel stack is supplied.

From a checkout, use the [development setup](../development/contributing.md) with Linux activation:

```sh
cd ~/Desktop/Sentinel
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m scripts.sentinel start
```

Configure router, providers, allowlists, and storage before starting. The default relative SQLite path depends on the working directory. Preserve database files and arrange backups; live presence/history buffers still reset on restart. PostgreSQL integration tests have passed, but target deployment, network-failure recovery, and backup restoration need separate validation.

ARP may require root-equivalent packet privileges or an appropriate capability; ICMP and router polling have different access needs. ARM dependency installation and actual LAN behavior must be checked on the target.

No systemd unit, complete Docker deployment, or K3s manifest is included. See [Docker](docker.md), [K3s](k3s.md), and [storage operations](../architecture/persistent-storage.md).
