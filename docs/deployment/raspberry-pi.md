# Raspberry Pi Deployment

Raspberry Pi is a supported design target, not a packaged deployment in the current repository. The current practical workflow is to install Python and the project dependencies in a virtual environment, configure `.env`, and run the integrated `sentinel start` process.

ARP scanning may require `CAP_NET_RAW` or equivalent privileges. Keep router credentials, bot tokens, webhook URLs, and allowlists outside source control. Persistent backups are not applicable yet because the registry and alert history are in memory.
