# syntax=docker/dockerfile:1.7
FROM python:3.14-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --upgrade \
    pip \
    "setuptools>=78.1.1" \
    && python -m pip install \
    "msgpack>=1.2.1" \
    '.[mlflow,otel]' \
    && python -m pip check \
    && python -m pip uninstall --yes pip \
    && python -c "import importlib.util; assert importlib.util.find_spec('pip') is None"

FROM python:3.14-slim-bookworm AS runtime

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ML_PLATFORM_STATE_DIR=/var/lib/ml-platform

RUN python -m pip uninstall --yes pip \
    && python -c "import importlib.util; assert importlib.util.find_spec('pip') is None" \
    && groupadd --gid 65532 platform \
    && useradd --uid 65532 --gid platform --no-create-home --shell /usr/sbin/nologin platform \
    && mkdir -p /var/lib/ml-platform \
    && chown -R platform:platform /var/lib/ml-platform

COPY --from=builder /opt/venv /opt/venv
USER 65532:65532
EXPOSE 8080
VOLUME ["/var/lib/ml-platform"]

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/readyz', timeout=2)"]

ENTRYPOINT ["ml-platform"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8080"]
