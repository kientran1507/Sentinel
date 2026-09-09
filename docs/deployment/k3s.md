# K3s Deployment

K3s is a future deployment target. Kubernetes manifests, persistent storage, service exposure, and secret wiring for Sentinel are not currently implemented in this repository.

When added, the monitor and command adapters should run in the same logical runtime or use a persistent state service. Splitting the current in-memory registry into separate pods would make `/devices` and `/alerts` incomplete.
