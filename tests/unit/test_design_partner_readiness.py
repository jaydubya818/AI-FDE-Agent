from __future__ import annotations

from argparse import Namespace
from typing import Any

import pytest

from scripts.verify_design_partner_readiness import (
    ReadinessFailure,
    _release_inputs,
    _verify_bedrock_evaluation,
    _verify_ecs,
)


class FakeECS:
    def __init__(self) -> None:
        self.rollback = True
        self.image_override: dict[str, str] = {}

    def describe_services(self, *, cluster: str, services: list[str]) -> dict[str, Any]:
        del cluster
        return {
            "failures": [],
            "services": [
                {
                    "serviceName": name,
                    "runningCount": 1,
                    "desiredCount": 1,
                    "taskDefinition": f"{name}:1",
                    "networkConfiguration": {"awsvpcConfiguration": {"assignPublicIp": "DISABLED"}},
                    "deploymentConfiguration": {
                        "deploymentCircuitBreaker": {
                            "enable": True,
                            "rollback": self.rollback,
                        }
                    },
                }
                for name in services
            ],
        }

    def describe_task_definition(self, *, taskDefinition: str) -> dict[str, Any]:
        runtime_name = (
            "migration" if taskDefinition == "alpha-migration" else taskDefinition.split(":")[0]
        )
        image = self.image_override.get(runtime_name, IMAGES[runtime_name])
        return {
            "taskDefinition": {
                "taskDefinitionArn": f"{runtime_name}:1",
                "requiresCompatibilities": ["FARGATE"],
                "networkMode": "awsvpc",
                "taskRoleArn": f"arn:aws:iam::123:role/{runtime_name}-task",
                "executionRoleArn": f"arn:aws:iam::123:role/{runtime_name}-execution",
                "containerDefinitions": [
                    {
                        "name": runtime_name,
                        "image": image,
                        "versionConsistency": "enabled",
                    }
                ],
            }
        }


class FakeBedrock:
    def __init__(self, *, status: str = "Completed", model: str = "profile-v1") -> None:
        self.status = status
        self.model = model

    def get_evaluation_job(self, *, jobIdentifier: str) -> dict[str, Any]:
        return {
            "jobArn": f"arn:aws:bedrock:us-east-1:123:evaluation-job/{jobIdentifier}",
            "jobName": jobIdentifier,
            "status": self.status,
            "applicationType": "ModelEvaluation",
            "inferenceConfig": {"models": [{"bedrockModel": {"modelIdentifier": self.model}}]},
        }


def _image(name: str) -> str:
    digest_character = {"web": "b", "api": "a", "worker": "c", "wrong": "d"}[name]
    return f"123.dkr.ecr.us-east-1.amazonaws.com/{name}@sha256:" + (digest_character * 64)


IMAGES = {
    "web": _image("web"),
    "api": _image("api"),
    "worker": _image("worker"),
    "migration": _image("api"),
}


def test_release_inputs_require_exact_commit_digests_and_external_evidence() -> None:
    args = Namespace(
        git_commit="a" * 40,
        web_image=IMAGES["web"],
        api_image=IMAGES["api"],
        worker_image=IMAGES["worker"],
        auth0_validation_id="auth0-2026-08-14",
        restore_rehearsal_id="restore-2026-08-14",
        deletion_rehearsal_id="delete-2026-08-14",
        secret_rotation_id="rotation-2026-08-14",
    )
    assert _release_inputs(args)["git_commit"] == "a" * 40

    args.git_commit = "main"
    with pytest.raises(ReadinessFailure, match="40-character"):
        _release_inputs(args)
    args.git_commit = "a" * 40
    args.web_image = "example/web:latest"
    with pytest.raises(ReadinessFailure, match="pinned"):
        _release_inputs(args)
    args.web_image = IMAGES["web"]
    args.auth0_validation_id = "pending"
    with pytest.raises(ReadinessFailure, match="completed external record"):
        _release_inputs(args)


def test_ecs_requires_release_images_rollback_and_version_consistency() -> None:
    client = FakeECS()
    result = _verify_ecs(
        client,
        cluster="alpha",
        services=["web", "api", "worker"],
        migration_family="alpha-migration",
        expected_images=IMAGES,
    )
    assert result["images"] == IMAGES
    assert result["deployment_rollback"] == "enabled"

    client.rollback = False
    with pytest.raises(ReadinessFailure, match="deployment rollback"):
        _verify_ecs(
            client,
            cluster="alpha",
            services=["web", "api", "worker"],
            migration_family="alpha-migration",
            expected_images=IMAGES,
        )
    client.rollback = True
    client.image_override["worker"] = _image("wrong")
    with pytest.raises(ReadinessFailure, match="release-bound image"):
        _verify_ecs(
            client,
            cluster="alpha",
            services=["web", "api", "worker"],
            migration_family="alpha-migration",
            expected_images=IMAGES,
        )


def test_bedrock_evaluation_must_be_complete_and_match_the_runtime_model() -> None:
    result = _verify_bedrock_evaluation(FakeBedrock(), "evaluation-v1", "profile-v1")
    assert result["job_status"] == "Completed"
    assert result["model_identifier"] == "profile-v1"

    with pytest.raises(ReadinessFailure, match="not completed"):
        _verify_bedrock_evaluation(FakeBedrock(status="InProgress"), "evaluation-v1", "profile-v1")
    with pytest.raises(ReadinessFailure, match="was not evaluated"):
        _verify_bedrock_evaluation(FakeBedrock(), "evaluation-v1", "profile-v2")
