"""Own a temporary native PostgreSQL cluster without using runtime configuration."""
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import tempfile
from uuid import uuid4


class LocalLabError(RuntimeError):
    pass


def find_postgres_bin(selected=None):
    if selected is not None:
        directory = Path(selected)
    elif shutil.which("initdb"):
        directory = Path(shutil.which("initdb")).parent
    else:
        directory = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "PostgreSQL/16/bin"
    suffix = ".exe" if os.name == "nt" else ""
    if any(not (directory / (name + suffix)).is_file() for name in ("initdb", "pg_ctl", "postgres")):
        raise LocalLabError("PostgreSQL binaries unavailable; select an existing installation with --pg-bin")
    return directory.resolve()


class LocalPostgreSQL:
    def __init__(self, pg_bin=None):
        self.bin = find_postgres_bin(pg_bin)
        self.root = Path(tempfile.mkdtemp(prefix="sentinel-local-lab-")).resolve()
        self._created_root = self.root
        self.nonce = uuid4().hex
        self.data = self.root / "data"
        (self.root / "owner.json").write_text(json.dumps({"nonce": self.nonce}), encoding="utf-8")
        self.role = "sentinel_lab_" + self.nonce[:12]
        self.password = secrets.token_urlsafe(32)
        self.database_url = None
        self.start_attempted = False
        self.init_attempted = False
        self.initialized = False
        self.ready = False
        self.outage_stopped = False
        self.cleanup = {"stopped": False, "data_removed": False}

    def _owned(self):
        if (self.root != self._created_root or self.root.is_symlink()
                or self.root.parent != Path(tempfile.gettempdir()).resolve()
                or not self.root.name.startswith("sentinel-local-lab-")
                or self.data != self.root / "data" or self.data.is_symlink()
                or (self.root / "owner.json").is_symlink()
                or json.loads((self.root / "owner.json").read_text(encoding="utf-8")) != {"nonce": self.nonce}):
            raise LocalLabError("temporary cluster ownership check failed")

    def _run(self, name, *args, timeout=25):
        suffix = ".exe" if os.name == "nt" else ""
        command = [str(self.bin / (name + suffix)), *map(str, args)]
        # A background Windows server can inherit pipe handles and prevent communicate()
        # from reaching EOF even after pg_ctl exits. File capture keeps wait bounded.
        capture = self.root / ("command-" + uuid4().hex + ".log")
        with capture.open("w+", encoding="utf-8", errors="replace") as stream:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=timeout,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            stream.seek(0)
            return subprocess.CompletedProcess(command, result.returncode, stream.read(65536), "")

    def start(self):
        import psycopg
        from psycopg.conninfo import make_conninfo

        self._owned()
        if any(os.environ.get(name) for name in ("PGSERVICE", "PGSERVICEFILE", "PGSYSCONFDIR")):
            raise LocalLabError("libpq service overrides are active; use a shell without service overrides")
        password_file = self.root / "password"
        with password_file.open("x", encoding="utf-8") as stream:
            stream.write(self.password + "\n")
        password_file.chmod(0o600)
        self.init_attempted = True
        result = self._run("initdb", "-D", self.data, "-U", self.role,
                           "--auth=scram-sha-256", "--pwfile", password_file,
                           "--encoding=UTF8", "--no-locale", "--no-instructions")
        (self.root / "initdb.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        if result.returncode:
            raise LocalLabError("temporary cluster initialization failed")
        self.initialized = True
        password_file.unlink()
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            self.port = reservation.getsockname()[1]
        options = (f"-h 127.0.0.1 -p {self.port} -c shared_buffers=16MB -c max_connections=20 "
                   "-c work_mem=1MB -c maintenance_work_mem=16MB -c max_wal_size=128MB")
        self.server_options = options
        self.start_attempted = True
        result = self._run("pg_ctl", "-D", self.data, "-l", self.root / "postgres.log",
                           "-w", "-t", "20", "start", "-o", options)
        if result.returncode:
            raise LocalLabError("temporary cluster startup failed; owned data retained")
        self.ready = True
        connection = dict(host="127.0.0.1", hostaddr="127.0.0.1", port=self.port,
                          user=self.role, password=self.password, sslmode="disable", gssencmode="disable",
                          client_encoding="UTF8", application_name="sentinel-local-lab",
                          connect_timeout=3, options="-c statement_timeout=5000 -c lock_timeout=2000")
        with psycopg.connect(make_conninfo(**connection, dbname="postgres"), autocommit=True) as admin:
            actual = admin.execute("SHOW data_directory").fetchone()[0]
            if Path(actual).resolve() != self.data.resolve():
                raise LocalLabError("connected server does not belong to local lab")
            self.version = admin.execute("SHOW server_version").fetchone()[0]
            admin.execute("CREATE DATABASE sentinel_local_lab")
        self.database_url = make_conninfo(**connection, dbname="sentinel_local_lab")

    def stop_for_outage(self):
        self._owned()
        if not self.ready or self.outage_stopped:
            raise LocalLabError("outage check requires the running owned cluster")
        if self._run("pg_ctl", "-D", self.data, "status", timeout=5).returncode != 0:
            raise LocalLabError("owned server not running before outage check")
        stopped = self._run("pg_ctl", "-D", self.data, "-m", "fast", "-w", "-t", "60", "stop", timeout=65)
        if stopped.returncode or self._run("pg_ctl", "-D", self.data, "status", timeout=5).returncode != 3:
            raise LocalLabError("owned outage stop unverified")
        self.outage_stopped = True

    def restart_after_outage(self):
        import psycopg

        self._owned()
        if not self.ready or not self.outage_stopped:
            raise LocalLabError("restart requires the verified owned outage stop")
        # Refuse to adopt a server that appeared while the owned cluster was stopped.
        if self._run("pg_ctl", "-D", self.data, "status", timeout=5).returncode != 3:
            raise LocalLabError("unexpected server state before owned restart")
        started = self._run("pg_ctl", "-D", self.data, "-l", self.root / "postgres.log",
                            "-w", "-t", "20", "start", "-o", self.server_options)
        if started.returncode:
            raise LocalLabError("owned database restart failed")
        with psycopg.connect(self.database_url) as connection:
            actual = connection.execute("SHOW data_directory").fetchone()[0]
            if Path(actual).resolve() != self.data.resolve():
                raise LocalLabError("restarted database ownership mismatch")
        self.outage_stopped = False

    def close(self):
        self._owned()
        if self.init_attempted and not self.initialized:
            raise LocalLabError("initialization incomplete; owned data retained")
        if self.start_attempted:
            status = self._run("pg_ctl", "-D", self.data, "status", timeout=5)
            if status.returncode == 0:
                stopped = self._run("pg_ctl", "-D", self.data, "-m", "fast", "-w", "-t", "60", "stop", timeout=65)
                if stopped.returncode or self._run("pg_ctl", "-D", self.data, "status", timeout=5).returncode != 3:
                    raise LocalLabError("temporary server stop unverified; owned data retained")
            elif status.returncode != 3 or self.ready:
                raise LocalLabError("unexpected temporary server state; owned data retained")
            self.cleanup["stopped"] = True
            if not self.ready:
                self.cleanup["retained_directory"] = str(self.root)
                return
        else:
            self.cleanup["stopped"] = True
        # Verify the resolved recursive-delete target stays inside our created temp directory.
        self._owned()
        if self.root.resolve() != self._created_root:
            raise LocalLabError("temporary cleanup target changed")
        shutil.rmtree(self.root)
        self.cleanup["data_removed"] = True
