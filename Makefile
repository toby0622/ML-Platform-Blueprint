.PHONY: install quality lint format type validate test pipeline demo api benchmark gpu-preflight gpu-up gpu-down gpu-benchmark

install:
	python -m pip install -e '.[dev]'

quality: lint format type validate test

lint:
	ruff check .

format:
	ruff format --check .

type:
	mypy

validate:
	python scripts/validate_repository.py

test:
	python -m pytest --cov --cov-report=term-missing

pipeline:
	python pipelines/training_pipeline/pipeline.py

demo:
	ml-platform --state-dir .ml-platform demo

api:
	ml-platform --state-dir .ml-platform serve --port 8080

benchmark:
	python benchmarks/load/run.py --base-url http://127.0.0.1:8080 --requests 500 --concurrency 20 --output benchmark-results/load.json

gpu-preflight:
	python scripts/gpu_preflight.py

gpu-up:
	docker compose --file compose.gpu.yaml up --detach

gpu-down:
	docker compose --file compose.gpu.yaml down

gpu-benchmark:
	python -m benchmarks.inference.run_local_gpu --scenario baseline
