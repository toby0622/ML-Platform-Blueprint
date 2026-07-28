"""Kubeflow Pipeline for validate -> train -> evaluate -> register."""

import os

from kfp import compiler, dsl

PIPELINE_IMAGE = os.getenv(
    "ML_PLATFORM_PIPELINE_IMAGE",
    "ghcr.io/example/ml-platform-blueprint-pipeline:0.1.0",
)


@dsl.container_component
def validate_data(
    samples: int,
    data_seed: int,
    dataset: dsl.Output[dsl.Dataset],
    dataset_metadata: dsl.Output[dsl.Artifact],
) -> dsl.ContainerSpec:
    return dsl.ContainerSpec(
        image=PIPELINE_IMAGE,
        command=["python", "-m", "ml_platform_blueprint.pipeline_components"],
        args=[
            "validate",
            "--samples",
            samples,
            "--data-seed",
            data_seed,
            "--output",
            dataset.path,
            "--metadata",
            dataset_metadata.path,
        ],
    )


@dsl.container_component
def train_model(
    dataset: dsl.Input[dsl.Dataset],
    dataset_metadata: dsl.Input[dsl.Artifact],
    split_seed: int,
    test_fraction: float,
    learning_rate: float,
    epochs: int,
    l2: float,
    decision_threshold: float,
    model: dsl.Output[dsl.Model],
    evaluation_data: dsl.Output[dsl.Dataset],
    parameters: dsl.Output[dsl.Artifact],
) -> dsl.ContainerSpec:
    return dsl.ContainerSpec(
        image=PIPELINE_IMAGE,
        command=["python", "-m", "ml_platform_blueprint.pipeline_components"],
        args=[
            "train",
            "--dataset",
            dataset.path,
            "--dataset-metadata",
            dataset_metadata.path,
            "--model",
            model.path,
            "--evaluation-data",
            evaluation_data.path,
            "--parameters",
            parameters.path,
            "--split-seed",
            split_seed,
            "--test-fraction",
            test_fraction,
            "--learning-rate",
            learning_rate,
            "--epochs",
            epochs,
            "--l2",
            l2,
            "--decision-threshold",
            decision_threshold,
        ],
    )


@dsl.container_component
def evaluate_model(
    model: dsl.Input[dsl.Model],
    evaluation_data: dsl.Input[dsl.Dataset],
    evaluation: dsl.Output[dsl.Metrics],
) -> dsl.ContainerSpec:
    return dsl.ContainerSpec(
        image=PIPELINE_IMAGE,
        command=["python", "-m", "ml_platform_blueprint.pipeline_components"],
        args=[
            "evaluate",
            "--model",
            model.path,
            "--evaluation-data",
            evaluation_data.path,
            "--metrics",
            evaluation.path,
            "--enforce-gate",
        ],
    )


@dsl.container_component
def register_model(
    model: dsl.Input[dsl.Model],
    parameters: dsl.Input[dsl.Artifact],
    evaluation: dsl.Input[dsl.Metrics],
    dataset_metadata: dsl.Input[dsl.Artifact],
    tracking_uri: str,
    experiment: str,
    tenant: str,
    model_name: str,
    pipeline_run_id: str,
    code_revision: str,
    registration: dsl.Output[dsl.Artifact],
) -> dsl.ContainerSpec:
    return dsl.ContainerSpec(
        image=PIPELINE_IMAGE,
        command=["python", "-m", "ml_platform_blueprint.pipeline_components"],
        args=[
            "register",
            "--model",
            model.path,
            "--parameters",
            parameters.path,
            "--metrics",
            evaluation.path,
            "--dataset-metadata",
            dataset_metadata.path,
            "--registration",
            registration.path,
            "--tracking-uri",
            tracking_uri,
            "--experiment",
            experiment,
            "--tenant",
            tenant,
            "--model-name",
            model_name,
            "--pipeline-run-id",
            pipeline_run_id,
            "--code-revision",
            code_revision,
        ],
    )


@dsl.pipeline(
    name="predictive-model-lifecycle",
    description="Validate, train, evaluate, gate, and register a predictive model.",
)
def training_pipeline(
    tenant: str = "team-a",
    model_name: str = "churn-classifier",
    samples: int = 800,
    data_seed: int = 42,
    split_seed: int = 42,
    test_fraction: float = 0.2,
    learning_rate: float = 0.12,
    epochs: int = 700,
    l2: float = 0.01,
    decision_threshold: float = 0.5,
    tracking_uri: str = "http://mlflow.ml-platform-system.svc.cluster.local:5000",
    experiment: str = "ml-platform-blueprint",
    code_revision: str = "set-by-ci",
) -> None:
    validation = validate_data(samples=samples, data_seed=data_seed)
    validation.set_caching_options(True)
    validation.set_retry(num_retries=2, backoff_duration="10s", backoff_factor=2.0)

    training = train_model(
        dataset=validation.outputs["dataset"],
        dataset_metadata=validation.outputs["dataset_metadata"],
        split_seed=split_seed,
        test_fraction=test_fraction,
        learning_rate=learning_rate,
        epochs=epochs,
        l2=l2,
        decision_threshold=decision_threshold,
    )
    training.set_caching_options(True)
    training.set_retry(num_retries=1)

    evaluation = evaluate_model(
        model=training.outputs["model"],
        evaluation_data=training.outputs["evaluation_data"],
    )
    evaluation.set_caching_options(False)

    register_model(
        model=training.outputs["model"],
        parameters=training.outputs["parameters"],
        evaluation=evaluation.outputs["evaluation"],
        dataset_metadata=validation.outputs["dataset_metadata"],
        tracking_uri=tracking_uri,
        experiment=experiment,
        tenant=tenant,
        model_name=model_name,
        pipeline_run_id=dsl.PIPELINE_JOB_ID_PLACEHOLDER,
        code_revision=code_revision,
    ).set_caching_options(False)


if __name__ == "__main__":
    compiler.Compiler().compile(
        pipeline_func=training_pipeline,
        package_path="pipeline.yaml",
    )
