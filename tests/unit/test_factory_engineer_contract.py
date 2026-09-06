from __future__ import annotations

import copy
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from ai_fde.modules.factory_engineer.canonical import (
    MAX_SAFE_JSON_INTEGER,
    CanonicalizationError,
    canonical_json_bytes,
    canonical_sha256,
)
from ai_fde.modules.factory_engineer.fixtures import SYNTHETIC_OPPORTUNITY_TEMPLATES
from ai_fde.modules.factory_engineer.readiness import (
    READINESS_CRITERIA,
    ReadinessCriteriaError,
    evaluate_readiness,
)
from ai_fde.modules.factory_engineer.schemas import (
    MAX_CODE_SCOPES,
    MAX_CONTRACT_ARRAY_ITEMS,
    DeploymentTarget,
    FactoryDeploymentPackageInput,
    FactoryDeploymentPackageStatus,
    FDLCStage,
    ImmutablePackageDocument,
    PackageAttestation,
    ProvenanceKind,
    PublishedPackageEnvelope,
    ReadinessAssessmentInput,
    ReadinessCriterionInput,
    ReadinessStageInput,
    ReadinessStatus,
    SourceReference,
)
from ai_fde.modules.factory_engineer.scoring import score_factory_opportunity
from ai_fde.modules.factory_engineer.service import MAX_PUBLISHED_ENVELOPE_BYTES

FIXTURE_PATH = Path("fixtures/contracts/factory-deployment-package-v1.json")
DIGEST_PATH = FIXTURE_PATH.with_suffix(".sha256")


def _fixture_payload() -> dict[str, object]:
    return cast(dict[str, object], json.loads(FIXTURE_PATH.read_text()))


def test_golden_package_fixture_has_cross_language_digest_and_valid_envelope() -> None:
    payload = _fixture_payload()
    declared = payload["integrity"]["digest"]  # type: ignore[index]
    expected = DIGEST_PATH.read_text().strip()
    digest_projection = copy.deepcopy(payload)
    integrity = digest_projection["integrity"]
    assert isinstance(integrity, dict)
    integrity.pop("digest")

    assert canonical_sha256(digest_projection) == expected == declared
    package = ImmutablePackageDocument.model_validate(payload)
    retrieved_at = package.issued_at + timedelta(minutes=2)
    envelope = PublishedPackageEnvelope(
        package=package,
        attestation=PackageAttestation(
            package_id=package.package_id,
            package_version=package.package_version,
            digest=package.integrity.digest,
            current_status=FactoryDeploymentPackageStatus.PUBLISHED,
            issuer=package.issuer,
            approval=package.approval,
            published_at=package.issued_at + timedelta(minutes=1),
            retrieved_at=retrieved_at,
            correlation_id=UUID("00000000-0000-4000-8000-000000000099"),
        ),
    )

    assert len(envelope.model_dump_json().encode("utf-8")) <= MAX_PUBLISHED_ENVELOPE_BYTES
    expected_scopes = package.target.requested_code_scopes
    assert all(
        blueprint.requested_code_scopes == expected_scopes
        for blueprint in package.deployment_intent.work_order_blueprints
    )


@pytest.mark.parametrize(
    "value",
    [
        {"non_ascii_\N{SNOWMAN}": "value"},
        {"float": 1.25},
        {"integer": MAX_SAFE_JSON_INTEGER + 1},
    ],
)
def test_canonical_json_rejects_nonportable_values(value: object) -> None:
    with pytest.raises(CanonicalizationError):
        canonical_json_bytes(value)


def test_canonical_json_sorts_keys_recursively_and_preserves_array_order() -> None:
    assert canonical_json_bytes({"z": [{"b": 1, "a": 2}], "a": [2, 1]}) == (
        b'{"a":[2,1],"z":[{"a":2,"b":1}]}'
    )


def _set_unknown_approval(value: dict[str, Any]) -> None:
    value["work_order_blueprints"][0]["required_approvals"] = ["missing-approval"]


def _append_second_blueprint(value: dict[str, Any]) -> dict[str, Any]:
    first = cast(dict[str, Any], value["work_order_blueprints"][0])
    second = copy.deepcopy(first)
    second["key"] = "validate-change"
    second["sequence"] = first["sequence"] + 1
    second["dependencies"] = [first["key"]]
    value["work_order_blueprints"].append(second)
    return second


def _set_forward_dependency(value: dict[str, Any]) -> None:
    second = _append_second_blueprint(value)
    value["work_order_blueprints"][0]["dependencies"] = [second["key"]]


def _duplicate_blueprint_key(value: dict[str, Any]) -> None:
    second = _append_second_blueprint(value)
    second["key"] = value["work_order_blueprints"][0]["key"]


def _add_unreferenced_criterion(value: dict[str, Any]) -> None:
    value["acceptance_criteria"].append(
        {
            "key": "criterion_unreferenced",
            "statement": "This criterion is intentionally not mapped.",
            "verification_method": "Run the focused test.",
        }
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (_set_unknown_approval, "unknown approval requirement"),
        (_set_forward_dependency, "earlier sequence"),
        (_duplicate_blueprint_key, "keys must be unique"),
        (_add_unreferenced_criterion, "Every acceptance criterion must be referenced"),
    ],
)
def test_package_plan_rejects_ambiguous_or_unexecutable_graphs(
    mutation: Callable[[dict[str, Any]], None], message: str
) -> None:
    raw = copy.deepcopy(_fixture_payload()["deployment_intent"])
    assert isinstance(raw, dict)
    mutation(raw)

    with pytest.raises(ValidationError, match=message):
        FactoryDeploymentPackageInput.model_validate(raw)


def test_shared_collection_and_code_scope_limits_are_exact() -> None:
    target = _fixture_payload()["target"]
    assert isinstance(target, dict)
    oversized_target = copy.deepcopy(target)
    oversized_target["requested_code_scopes"] = [
        f"src/scope-{index}" for index in range(MAX_CODE_SCOPES + 1)
    ]
    with pytest.raises(ValidationError, match="at most 50 items"):
        DeploymentTarget.model_validate(oversized_target)

    package_input = _fixture_payload()["deployment_intent"]
    assert isinstance(package_input, dict)
    oversized_input = copy.deepcopy(package_input)
    oversized_input["acceptance_criteria"] = [
        {
            "key": f"criterion-{index}",
            "statement": "Bounded criterion.",
            "verification_method": "TEST",
        }
        for index in range(MAX_CONTRACT_ARRAY_ITEMS + 1)
    ]
    with pytest.raises(ValidationError, match="at most 200 items"):
        FactoryDeploymentPackageInput.model_validate(oversized_input)


def _basis_ref() -> SourceReference:
    return SourceReference(
        kind=ProvenanceKind.EVIDENCE,
        ref="evidence:00000000-0000-4000-8000-000000000001",
        sha256="sha256:" + "a" * 64,
    )


def _ready_assessment() -> ReadinessAssessmentInput:
    stages = []
    for stage, keys in READINESS_CRITERIA.items():
        stages.append(
            ReadinessStageInput(
                stage=stage,
                criteria=[
                    ReadinessCriterionInput(
                        key=key,
                        label=key.replace("_", " ").title(),
                        satisfied=True,
                        explanation="Verified by the exact source reference.",
                        basis_refs=[_basis_ref()],
                    )
                    for key in keys
                ],
            )
        )
    return ReadinessAssessmentInput(stages=stages)


def test_readiness_is_evidence_backed_complete_and_explainable() -> None:
    now = datetime(2026, 9, 4, 16, tzinfo=UTC)
    overall, snapshots = evaluate_readiness(_ready_assessment(), now=now)

    assert overall == ReadinessStatus.READY
    assert [snapshot.stage for snapshot in snapshots] == list(FDLCStage)
    assert all(snapshot.status == ReadinessStatus.READY for snapshot in snapshots)
    assert all(snapshot.score == 100 for snapshot in snapshots)
    assert all(snapshot.evidence_refs == [_basis_ref()] for snapshot in snapshots)


def test_readiness_rejects_missing_required_criterion() -> None:
    assessment = _ready_assessment()
    assessment.stages[0].criteria.pop()

    with pytest.raises(ReadinessCriteriaError, match="criteria mismatch"):
        evaluate_readiness(assessment)


def test_three_factory_opportunity_fixtures_have_stable_explainable_scores() -> None:
    actual = {
        template.fixture_profile: score_factory_opportunity(template.factors)
        for template in SYNTHETIC_OPPORTUNITY_TEMPLATES
    }

    assert {
        key: (
            value.value_score,
            value.verifiability_score,
            value.readiness_score,
            value.risk_score,
            value.autonomy_potential,
            value.priority_score,
        )
        for key, value in actual.items()
    } == {
        "acme": (71, 95, 74, 53, 81, 77),
        "beacon": (85, 91, 81, 40, 92, 84),
        "northstar": (86, 89, 68, 95, 50, 70),
    }
    assert actual["acme"].recommendation.startswith("RECOMMEND")
    assert actual["beacon"].recommendation.startswith("RECOMMEND")
    assert actual["northstar"].recommendation.startswith("ASSESS")
    assert all(score.rationale for score in actual.values())
