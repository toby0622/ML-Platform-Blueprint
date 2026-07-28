# syntax=docker/dockerfile:1.7
FROM ghcr.io/mlflow/mlflow:v3.14.0

RUN python -m pip install --no-cache-dir \
    "boto3>=1.35,<2" \
    "psycopg2-binary>=2.9.10,<3"

USER 1000:1000
