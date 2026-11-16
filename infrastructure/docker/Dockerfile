# syntax=docker/dockerfile:1
ARG PYTHON_IMAGE=python:3.11-slim-bookworm@sha256:a83ba18aef0f865b1a4a611c2cf460fe446f2795673bbb9fe43be570439e3b39

FROM ${PYTHON_IMAGE} AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN python -m venv /opt/venv
COPY infrastructure/docker/requirements.lock /build/requirements.lock
RUN /opt/venv/bin/python -m pip install --require-hashes --only-binary=:all: --no-deps -r /build/requirements.lock
WORKDIR /build/app
COPY pyproject.toml setup.cfg ./
COPY services ./services
COPY scripts ./scripts
RUN /opt/venv/bin/python -m pip install --no-deps --no-build-isolation . \
    && /opt/venv/bin/python -m pip check

FROM ${PYTHON_IMAGE} AS runtime
RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates tini systemd iproute2 iputils-ping nftables iptables \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 sentinel \
    && useradd --uid 10001 --gid sentinel --no-create-home --home-dir /tmp --shell /usr/sbin/nologin sentinel
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HOME=/tmp \
    SENTINEL_STORAGE_BACKEND=postgresql
WORKDIR /opt/sentinel
USER 10001:10001
ENTRYPOINT ["/usr/bin/tini", "--", "/opt/venv/bin/python", "-m", "scripts.container_entrypoint"]
CMD ["sentinel", "start"]

FROM runtime AS test
COPY tests /opt/sentinel/tests
CMD ["python", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]
