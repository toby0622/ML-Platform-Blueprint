# syntax=docker/dockerfile:1.7
FROM ghcr.io/mlflow/mlflow:v3.14.0

USER 0:0

# The upstream image can lag Debian and Python security updates. Apply available
# fixes before dropping privileges so the release image passes the HIGH/CRITICAL gate.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get upgrade --yes --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir --upgrade \
    "GitPython>=3.1.51,<4" \
    "Pillow>=12.3.0,<13" \
    "msgpack>=1.2.1" \
    "pyasn1>=0.6.4,<0.7" \
    "setuptools>=78.1.1" \
    "wheel>=0.46.2,<1" \
    "boto3>=1.35,<2" \
    "psycopg2-binary>=2.9.10,<3" \
    && python -m pip check \
    && python -m pip uninstall --yes pip \
    && python -c "import importlib.util; assert importlib.util.find_spec('pip') is None"

USER 1000:1000
