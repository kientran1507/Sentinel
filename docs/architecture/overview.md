# Architecture Overview

Sentinel is a self-hosted monitoring platform for small infrastructure and homelab environments. It combines device discovery, health monitoring, metrics collection, and alerting into a single system that can run on lightweight hardware or in a small Kubernetes cluster.

## What Sentinel Is

Sentinel provides a central place to discover devices, observe their state, and surface actionable alerts. The goal is to reduce the number of separate tools needed to monitor a small environment while keeping the platform simple enough to deploy and operate locally.

## Problem It Solves

Small teams and homelab operators often need to piece together discovery, metrics, alerting, and visualization from multiple tools. Sentinel is intended to unify those concerns into one deployable system with a clear data flow and a small operational footprint.

## Service Communication

The dashboard talks to a REST API exposed by Sentinel Core. Core coordinates the monitoring workflow and exchanges data with the discovery, monitoring, and alerting services. Shared configuration and infrastructure components provide the runtime environment and persistence needed by those services.

## Data Storage

Sentinel will store configuration, discovered device state, collected metrics, and alert history in project-backed storage that can be mounted locally or managed through the chosen deployment target. The exact storage backend will be defined as implementation work progresses.

## Device To Alert Flow

1. A discovery job finds or refreshes devices on the network.
2. Monitoring checks collect health and metrics data from those devices.
3. The alerting layer evaluates that data against configured thresholds and conditions.
4. The dashboard and API present the resulting status, history, and active alerts.

## Guiding Diagram

The first architecture diagram will anchor the implementation shape of the project and will be kept in sync with this document as the platform grows.

## Status

This is the first design draft and will evolve as services are implemented.
