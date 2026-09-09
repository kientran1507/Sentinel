# Docker Deployment

Docker deployment is a future packaging target. The repository does not currently provide a complete Sentinel image, Compose service, persistent volume contract, or production startup manifest.

For local development, use the Python virtual environment documented in the [README](../../README.md). If packaging Sentinel in Docker, keep the integrated `sentinel start` process as the owner of the shared `DeviceRegistry`, `PresenceTracker`, `EventBus`, `AlertEngine`, `AlertHistory`, and command service. Mount configuration through environment variables or a secret store; never bake `.env` into an image.
