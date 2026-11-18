"""Characterization tests for the pure target-recommendation helper.

Extends docs/NIGHTLY-BACKLOG.md's 2026-09-01 coverage-gap entry
("Service-layer coverage is gated on Docker"): `_target_recommendation`
in `ai_fde.modules.workflows.service` takes a single `WorkflowStep` and
touches no `Session` or database, but the only paths that exercise it
today run through `generate_target_workflow`, which is only covered by
`tests/acceptance` / `tests/isolation` suites marked `@pytest.mark.integration`
or `@pytest.mark.isolation` -- both skip without a Docker daemon. This
function does not need separating to be tested on its own -- it already
is pure -- so this pins its three branches directly, no Docker required.
"""

from __future__ import annotations

import uuid

from ai_fde.models import WorkflowStep
from ai_fde.modules.workflows.service import _target_recommendation


def _step(*, step_type: str, system_label: str | None) -> WorkflowStep:
    return WorkflowStep(
        id=uuid.uuid4(),
        engagement_id=uuid.uuid4(),
        workflow_version_id=uuid.uuid4(),
        step_key="step",
        position=0,
        name="Step",
        description="A step.",
        step_type=step_type,
        system_label=system_label,
        allocation="human",
        rationale="",
        controls=[],
    )


def test_approval_steps_always_recommend_human_allocation() -> None:
    step = _step(step_type="approval", system_label="Some System")
    allocation, rationale, controls = _target_recommendation(step)
    assert allocation == "human"
    assert "approval authority" in rationale
    assert controls == [
        "Approval actor and decision are recorded",
        "No autonomous approval",
    ]


def test_a_non_approval_step_with_a_system_label_recommends_software() -> None:
    step = _step(step_type="software_task", system_label="Billing Ledger")
    allocation, rationale, controls = _target_recommendation(step)
    assert allocation == "software"
    assert rationale == (
        "Preserve Billing Ledger as the deterministic system of record."
    )
    assert controls == [
        "Existing system of record is preserved",
        "Failures route to a human owner",
    ]


def test_a_non_approval_step_with_no_system_label_falls_back_to_human() -> None:
    step = _step(step_type="human_task", system_label=None)
    allocation, rationale, controls = _target_recommendation(step)
    assert allocation == "human"
    assert rationale == "Insufficient verified evidence exists to justify higher autonomy."
    assert controls == ["Named human owner remains accountable"]


def test_approval_takes_priority_over_a_system_label() -> None:
    # An approval step with a system_label still recommends human allocation --
    # the step_type check runs first and short-circuits the system_label branch.
    step = _step(step_type="approval", system_label="Billing Ledger")
    allocation, _rationale, _controls = _target_recommendation(step)
    assert allocation == "human"
