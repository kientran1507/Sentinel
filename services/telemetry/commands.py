"""Bounded command output without shell execution or privilege escalation."""
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from time import monotonic

MAX_OUTPUT_BYTES = 4 * 1024 * 1024


class SourceUnavailable(RuntimeError):
    pass


def read_command(arguments, *, timeout=10, max_bytes=MAX_OUTPUT_BYTES):
    executable = shutil.which(arguments[0])
    if executable is None:
        raise SourceUnavailable("command_missing")
    deadline = monotonic() + timeout
    with subprocess.Popen([executable, *arguments[1:]], stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False) as process:
        with ThreadPoolExecutor(max_workers=2) as executor:
            stdout = executor.submit(process.stdout.read, max_bytes + 1)
            stderr = executor.submit(process.stderr.read, 65537)
            try:
                output = stdout.result(timeout=max(0.01, deadline - monotonic()))
                if len(output) > max_bytes:
                    raise SourceUnavailable("output_limit")
                diagnostic = stderr.result(timeout=max(0.01, deadline - monotonic()))
                if len(diagnostic) > 65536:
                    raise SourceUnavailable("output_limit")
                code = process.wait(timeout=max(0.01, deadline - monotonic()))
                if code != 0:
                    raise SourceUnavailable("command_failed")
                # journalctl can report restricted journal access with exit code 0.
                if diagnostic.strip():
                    raise SourceUnavailable("command_diagnostic")
                return output.decode("utf-8", errors="strict")
            except BaseException:
                if process.poll() is None:
                    process.kill()
                process.wait()
                raise
