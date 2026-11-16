"""Load mounted Sentinel configuration and replace this process with the command."""
import os
from pathlib import Path
import re
import sys


MAX_CONFIG_BYTES = 64 * 1024
CONFIG_PREFIXES = ("SENTINEL_", "ZTE_", "DISCORD_", "TELEGRAM_")


def container_environment(environ):
    environment = dict(environ)
    path = environment.get("SENTINEL_CONFIG_FILE")
    if not path:
        return environment
    with Path(path).open("rb") as stream:
        content = stream.read(MAX_CONFIG_BYTES + 1)
    if len(content) > MAX_CONFIG_BYTES:
        raise ValueError("configuration size limit exceeded")
    declared = set()
    for line in content.decode("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or re.fullmatch(r"[A-Z][A-Z0-9_]*", key) is None:
            raise ValueError("invalid configuration assignment")
        if not key.startswith(CONFIG_PREFIXES) or key in declared:
            raise ValueError("unsupported or duplicate configuration key")
        declared.add(key)
        environment.setdefault(key, value.strip().strip("'\"").replace("\\n", "\n"))
    return environment


def main(argv=None):
    command = list(sys.argv[1:] if argv is None else argv)
    if not command:
        command = ["sentinel", "start"]
    try:
        environment = container_environment(os.environ)
        os.execvpe(command[0], command, environment)
    except Exception as exc:
        print(f"Container startup failed ({type(exc).__name__}).", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
