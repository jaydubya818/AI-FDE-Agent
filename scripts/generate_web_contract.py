from __future__ import annotations

# ruff: noqa: E402 -- make the repository source importable when the script runs directly.
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, get_args

from pydantic import BaseModel
from sqlalchemy import CheckConstraint

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_fde.adapters.extraction import PREDICATES
from ai_fde.api.schemas import (
    AssertionResponse,
    ClaimResponse,
    ContradictionResolveRequest,
    ContradictionResponse,
    DeliveryScorecardResponse,
    EconomicCaseResponse,
    EngagementAssessmentResponse,
    EngagementDataLifecycleResponse,
    EngagementDeletionReceiptResponse,
    EngagementResponse,
    EngagementWorkspaceResponse,
    EntityResponse,
    EvidenceResponse,
    ImplementationArtifactResponse,
    InternalAlphaScorecardResponse,
    OperatingModelResponse,
    ProvenanceResponse,
    WorkflowResponse,
    WorkflowStepResponse,
    WorkflowWorkspaceResponse,
)
from ai_fde.config import Settings
from ai_fde.models import (
    Assertion,
    CandidateClaim,
    Contradiction,
    EconomicCase,
    Engagement,
    EngagementAssessment,
    EngagementDeletionReceipt,
    EvidenceAsset,
    ImplementationArtifact,
    OperatingEntity,
    WorkflowStep,
    WorkflowVersion,
)

OUTPUT = ROOT / "apps/web/lib/backend-contract.generated.ts"

RESPONSE_MODELS: dict[str, type[BaseModel]] = {
    "assertion": AssertionResponse,
    "claim": ClaimResponse,
    "contradiction": ContradictionResponse,
    "deliveryScorecard": DeliveryScorecardResponse,
    "economicCase": EconomicCaseResponse,
    "engagement": EngagementResponse,
    "engagementAssessment": EngagementAssessmentResponse,
    "engagementDataLifecycle": EngagementDataLifecycleResponse,
    "engagementDeletionReceipt": EngagementDeletionReceiptResponse,
    "engagementWorkspace": EngagementWorkspaceResponse,
    "entity": EntityResponse,
    "evidence": EvidenceResponse,
    "implementationArtifact": ImplementationArtifactResponse,
    "internalAlphaScorecard": InternalAlphaScorecardResponse,
    "operatingModel": OperatingModelResponse,
    "provenance": ProvenanceResponse,
    "workflow": WorkflowResponse,
    "workflowStep": WorkflowStepResponse,
    "workflowWorkspace": WorkflowWorkspaceResponse,
}


def _check_values(model: type[Any], field_name: str) -> list[str]:
    pattern = re.compile(rf"\b{re.escape(field_name)}\s+IN\s*\((.*?)\)", re.IGNORECASE)
    for constraint in model.__table__.constraints:
        if not isinstance(constraint, CheckConstraint):
            continue
        match = pattern.search(str(constraint.sqltext))
        if match:
            return re.findall(r"'([^']+)'", match.group(1))
    raise RuntimeError(f"No IN constraint found for {model.__tablename__}.{field_name}")


def _request_enum(model: type[Any], field_name: str) -> list[str]:
    schema = model.model_json_schema()
    values = schema["properties"][field_name].get("enum")
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
        raise RuntimeError(f"No string enum found for {model.__name__}.{field_name}")
    return values


def _settings_literal(field_name: str) -> list[str]:
    values = list(get_args(Settings.model_fields[field_name].annotation))
    if not values or not all(isinstance(item, str) for item in values):
        raise RuntimeError(f"No string Literal found for Settings.{field_name}")
    return values


def contract() -> dict[str, object]:
    enums = {
        "assertionStatus": _check_values(Assertion, "status"),
        "assessmentDeliveryMethod": _check_values(EngagementAssessment, "delivery_method"),
        "assessmentOutcome": _check_values(EngagementAssessment, "outcome"),
        "assessmentPerspective": _check_values(EngagementAssessment, "perspective"),
        "claimKind": _check_values(CandidateClaim, "claim_kind"),
        "claimMateriality": _check_values(CandidateClaim, "materiality"),
        "claimPredicate": sorted(PREDICATES),
        "claimStatus": _check_values(CandidateClaim, "status"),
        "contradictionResolutionType": _request_enum(
            ContradictionResolveRequest, "resolution_type"
        ),
        "contradictionStatus": _check_values(Contradiction, "status"),
        "economicCaseStatus": _check_values(EconomicCase, "status"),
        "engagementDataClassification": _check_values(Engagement, "data_classification"),
        "engagementDataLifecycleStatus": _check_values(
            Engagement, "data_lifecycle_status"
        ),
        "engagementLifecycleStage": _check_values(Engagement, "lifecycle_stage"),
        "entityType": _check_values(OperatingEntity, "entity_type"),
        "evidenceSourceType": _check_values(EvidenceAsset, "source_type"),
        "evidenceStatus": _check_values(EvidenceAsset, "status"),
        "artifactStatus": _check_values(ImplementationArtifact, "status"),
        "artifactType": _check_values(ImplementationArtifact, "artifact_type"),
        "operatorAuthMode": _settings_literal("auth_mode"),
        "deletionReceiptDataClassification": _check_values(
            EngagementDeletionReceipt, "data_classification"
        ),
        "deletionReceiptStatus": _check_values(EngagementDeletionReceipt, "status"),
        "workflowAllocation": _check_values(WorkflowStep, "allocation"),
        "workflowGeneratedBy": _check_values(WorkflowVersion, "generated_by"),
        "workflowKind": _check_values(WorkflowVersion, "workflow_kind"),
        "workflowStatus": _check_values(WorkflowVersion, "status"),
        "workflowStepType": _check_values(WorkflowStep, "step_type"),
    }
    required_fields = {
        name: model.model_json_schema().get("required", [])
        for name, model in RESPONSE_MODELS.items()
    }
    return {"enums": enums, "requiredResponseFields": required_fields}


def render_contract() -> str:
    serialized = json.dumps(contract(), indent=2, sort_keys=True)
    return (
        "// Generated by scripts/generate_web_contract.py. Do not edit by hand.\n"
        f"export const BACKEND_CONTRACT = {serialized} as const;\n\n"
        "export type BackendEnum<\n"
        "  Name extends keyof typeof BACKEND_CONTRACT.enums,\n"
        "> = (typeof BACKEND_CONTRACT.enums)[Name][number];\n\n"
        "export type MissingBackendFields<\n"
        "  Name extends keyof typeof BACKEND_CONTRACT.requiredResponseFields,\n"
        "  Value,\n"
        "> = Exclude<\n"
        "  (typeof BACKEND_CONTRACT.requiredResponseFields)[Name][number],\n"
        "  keyof Value\n"
        ">;\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--print", dest="print_output", action="store_true")
    args = parser.parse_args()
    rendered = render_contract()
    if args.print_output:
        print(rendered, end="")
        return
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text() != rendered:
            raise SystemExit(
                "The generated web contract is stale. Run "
                "`uv run python scripts/generate_web_contract.py`."
            )
        return
    OUTPUT.write_text(rendered)


if __name__ == "__main__":
    main()
