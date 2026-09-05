import type {
  CustomerFactoryModel,
  CustomerFactoryModelInput,
  DeploymentPackageInput,
  DesignPartnerQualification,
  EconomicCase,
  FactoryHandoffPrerequisites,
  FactoryOpportunity,
  FactoryOpportunityFactors,
  FactoryOpportunityInput,
  FactorySourceReference,
  FDLCReadinessAssessment,
  FDLCReadinessStage,
  ImplementationArtifact,
  ReadinessAssessmentInput,
} from "./types";

export const READINESS_CRITERIA: Record<
  FDLCReadinessStage["stage"],
  readonly string[]
> = {
  DISCOVER: [
    "desired_outcome",
    "owner",
    "workflow_scope",
    "baseline_evidence",
    "evidence_sufficiency",
    "material_unknowns",
  ],
  DESIGN: [
    "current_state_approved",
    "target_state_defined",
    "acceptance_criteria",
    "work_allocation",
    "autonomy_boundary",
    "authority_boundary",
  ],
  ASSEMBLE: [
    "agents",
    "skills",
    "tools",
    "models",
    "context_sources",
    "environment",
  ],
  VALIDATE: [
    "verification_strategy",
    "evaluation_requirements",
    "security_requirements",
    "failure_handling",
    "rollback",
    "permission_model",
    "unresolved_blockers",
  ],
  DEPLOY: [
    "deployment_scope",
    "rollout_plan",
    "approval_requirements",
    "deployment_package",
    "production_target",
  ],
  OPERATE: [
    "ownership",
    "observability",
    "incident_response",
    "cost_monitoring",
    "human_escalation",
  ],
  IMPROVE: [
    "outcome_metrics",
    "baseline",
    "learning_signals",
    "failure_taxonomy",
    "improvement_owner",
  ],
};

export const READINESS_STAGES = Object.keys(READINESS_CRITERIA) as Array<
  FDLCReadinessStage["stage"]
>;

export const READINESS_CRITERION_COUNT = READINESS_STAGES.reduce(
  (total, stage) => total + READINESS_CRITERIA[stage].length,
  0,
);

export function readinessCriterionReviewKey(
  stage: FDLCReadinessStage["stage"],
  criterion: string,
): string {
  return `${stage}:${criterion}`;
}

export const DEFAULT_OPPORTUNITY_FACTORS: FactoryOpportunityFactors = {
  workflow_frequency: 3,
  human_effort: 3,
  cycle_time: 3,
  repeatability: 3,
  standardization: 3,
  evidence_quality: 3,
  deterministic_verifiability: 3,
  blast_radius: 2,
  system_accessibility: 3,
  data_sensitivity: 3,
  implementation_complexity: 3,
  expected_economic_value: 3,
  autonomy_potential: 2,
};

export function buildCustomerFactoryModelInput(
  prerequisites: FactoryHandoffPrerequisites,
  qualification: DesignPartnerQualification,
): CustomerFactoryModelInput {
  const evidence = prerequisites.evidence_refs[0];
  const verifiedClaim = prerequisites.verified_claim_refs[0];
  if (!evidence || !verifiedClaim) {
    throw new Error(
      "Complete evidence review and accept at least one claim before building the customer model.",
    );
  }
  const provenance = [verifiedClaim, evidence];
  return {
    organization: {
      key: prerequisites.organization_key,
      label: qualification.organization,
      description: `Qualified design-partner context for ${prerequisites.workflow_name}.`,
      provenance_refs: provenance,
      attributes: {
        partner_key: qualification.partner_key,
        data_classification: qualification.data_classification,
      },
    },
    systems: [],
    repositories: qualification.authorized_repository_refs.map(
      (repository) => ({
        key: factoryKey(repository),
        label: repository,
        description:
          "Repository explicitly authorized by the design-partner qualification.",
        provenance_refs: provenance,
        attributes: {
          authorization_basis: qualification.authorization_basis_ref,
        },
      }),
    ),
    environments: [],
    workflows: [
      {
        key: factoryKey(prerequisites.workflow_name),
        label: prerequisites.workflow_name,
        description: prerequisites.primary_outcome,
        provenance_refs: provenance,
        attributes: {
          allowed_workflow_classes: qualification.allowed_workflow_classes,
        },
      },
    ],
    policies: [],
    authority_boundaries: [
      {
        key: "human-governed-handoff",
        label: "Human-governed draft handoff",
        description:
          "Factory Engineer may prepare and publish a reviewed package; Mission Control receives draft intent and retains all execution authority.",
        provenance_refs: provenance,
        attributes: {
          maximum_authority: "DEPLOYMENT_PACKAGE_PUBLISH",
          prohibited_actions: [
            "approve Mission Control plan",
            "dispatch work",
            "merge",
            "release",
            "deploy",
          ],
        },
      },
    ],
    constraints: [
      {
        key: "qualified-customer-boundary",
        label: "Qualified customer-data boundary",
        description:
          "Use only the authorized design-partner sources, workflow classes, repositories, classification, and retention window.",
        provenance_refs: provenance,
        attributes: { qualification_id: qualification.id },
      },
    ],
    risks: [
      {
        key: "draft-authority-only",
        label: "No production mutation authority",
        description:
          "Generated recommendations and packages are advisory until separately governed downstream human decisions occur.",
        provenance_refs: provenance,
        attributes: {},
      },
    ],
    baselines: [],
    evidence_refs: prerequisites.evidence_refs,
    verified_claim_refs: prerequisites.verified_claim_refs,
    assumption_refs: [],
    factory_opportunity_refs: [],
  };
}

export function buildFactoryOpportunityInput({
  model,
  prerequisites,
  name,
  description,
  factors,
}: {
  model: CustomerFactoryModel;
  prerequisites: FactoryHandoffPrerequisites;
  name: string;
  description: string;
  factors: FactoryOpportunityFactors;
}): FactoryOpportunityInput {
  if (!prerequisites.current_workflow_ref || !prerequisites.economic_case_ref) {
    throw new Error(
      "Approve the current workflow and economic case before assessing a factory opportunity.",
    );
  }
  return {
    customer_factory_model_id: model.id,
    opportunity: {
      opportunity_key: factoryKey(name),
      name: name.trim(),
      description: description.trim(),
      source_workflow_ref: prerequisites.current_workflow_ref,
      factors,
      economics_ref: prerequisites.economic_case_ref,
      evidence_refs: model.evidence_refs,
      blockers: [],
    },
  };
}

export function buildReadinessAssessmentInput({
  model,
  opportunity,
  prerequisites,
  reviewedCriteria,
  owner,
}: {
  model: CustomerFactoryModel;
  opportunity: FactoryOpportunity;
  prerequisites: FactoryHandoffPrerequisites;
  reviewedCriteria: ReadonlySet<string>;
  owner: string;
}): ReadinessAssessmentInput {
  if (
    !prerequisites.current_workflow_ref ||
    !prerequisites.target_workflow_ref
  ) {
    throw new Error(
      "Approve the current and target workflows before assessing readiness.",
    );
  }
  if (prerequisites.implementation_artifact_refs.length === 0) {
    throw new Error(
      "Generate the current implementation packet before assessing readiness.",
    );
  }
  const expectedCriteria = READINESS_STAGES.flatMap((stage) =>
    READINESS_CRITERIA[stage].map((criterion) =>
      readinessCriterionReviewKey(stage, criterion),
    ),
  );
  if (
    reviewedCriteria.size !== expectedCriteria.length ||
    expectedCriteria.some((criterion) => !reviewedCriteria.has(criterion))
  ) {
    throw new Error(
      "Review and confirm every FDLC readiness criterion before recording readiness.",
    );
  }
  const currentWorkflow = approvedWorkflowReference(
    prerequisites.current_workflow_ref,
  );
  const targetWorkflow = approvedWorkflowReference(
    prerequisites.target_workflow_ref,
  );
  const decisions = [currentWorkflow, targetWorkflow];
  return {
    customer_factory_model_id: model.id,
    selected_opportunity_id: opportunity.id,
    current_workflow_id: prerequisites.current_workflow_ref.id,
    target_workflow_id: prerequisites.target_workflow_ref.id,
    assessment: {
      stages: READINESS_STAGES.map((stage) => {
        const basis = readinessBasis(stage, prerequisites);
        return {
          stage,
          criteria: READINESS_CRITERIA[stage].map((key) => {
            const satisfied = reviewedCriteria.has(
              readinessCriterionReviewKey(stage, key),
            );
            return {
              key,
              label: humanize(key),
              satisfied,
              blocking: true,
              explanation: satisfied
                ? "Confirmed by the human operator against this criterion's listed immutable Factory Engineer basis."
                : "This criterion has not been confirmed by the human operator.",
              basis_refs: satisfied ? basis : [],
              next_action: satisfied
                ? null
                : `Review and confirm ${humanize(key)}.`,
            };
          }),
          risks:
            stage === "DEPLOY"
              ? [
                  "This assessment permits draft-package preparation only; it grants no merge, release, deployment, or downstream approval authority.",
                ]
              : [],
          decisions,
          required_artifacts: prerequisites.implementation_artifact_refs.map(
            (reference) => reference.ref,
          ),
          owner: owner.trim() || "Design-partner operator",
        };
      }),
    },
  };
}

export function buildDeploymentPackageInput({
  model,
  opportunity,
  readiness,
  prerequisites,
  qualification,
  economics,
  artifacts,
  repositoryRef,
  workflowClass,
  requestedCodeScopes,
  missionTitle,
  objective,
}: {
  model: CustomerFactoryModel;
  opportunity: FactoryOpportunity;
  readiness: FDLCReadinessAssessment;
  prerequisites: FactoryHandoffPrerequisites;
  qualification: DesignPartnerQualification;
  economics: EconomicCase;
  artifacts: ImplementationArtifact[];
  repositoryRef: string;
  workflowClass: string;
  requestedCodeScopes: string[];
  missionTitle: string;
  objective: string;
}): DeploymentPackageInput {
  const implementationSpec = artifacts.find(
    (artifact) => artifact.artifact_type === "implementation_spec",
  );
  if (!implementationSpec) {
    throw new Error("The current implementation specification is unavailable.");
  }
  const implementationSpecReference =
    prerequisites.implementation_artifact_refs.find(
      (reference) =>
        reference.ref === `implementation_artifact:${implementationSpec.id}` &&
        reference.version === implementationSpec.version_number,
    );
  if (!implementationSpecReference) {
    throw new Error(
      "The current implementation specification has no approved immutable reference.",
    );
  }
  if (!qualification.authorized_repository_refs.includes(repositoryRef)) {
    throw new Error("Choose a repository authorized by this qualification.");
  }
  if (!qualification.allowed_workflow_classes.includes(workflowClass)) {
    throw new Error(
      "Choose a workflow class authorized by this qualification.",
    );
  }
  if (requestedCodeScopes.length === 0) {
    throw new Error("Record at least one bounded code scope.");
  }
  const readinessRef: FactorySourceReference = {
    kind: "APPROVED_INPUT",
    ref: `fdlc_readiness:${readiness.id}`,
    version: readiness.version_number,
    sha256: readiness.content_digest,
  };
  const provenance = uniqueReferences([
    ...model.evidence_refs,
    ...model.verified_claim_refs,
    ...(prerequisites.economic_case_ref
      ? [prerequisites.economic_case_ref]
      : []),
    ...prerequisites.implementation_artifact_refs,
    readinessRef,
  ]);
  const acceptanceCriteria = [
    {
      key: "bounded-change",
      statement:
        "Every change remains inside the exact human-approved code scope.",
      verification_method: "CHECKLIST",
    },
    {
      key: "verification-green",
      statement:
        "Independent validation passes on the exact candidate revision before acceptance.",
      verification_method: "TEST",
    },
  ];
  return {
    customer_factory_model_id: model.id,
    readiness_assessment_id: readiness.id,
    factory_opportunity_id: opportunity.id,
    target: {
      workspace_ref: `mission-control://design-partner/${qualification.partner_key}`,
      repository_ref: repositoryRef,
      requested_code_scopes: requestedCodeScopes,
      semantic_execution_workflow_ref: workflowClass,
      environment_class: "ISOLATED_NON_PRODUCTION",
    },
    deployment_intent: {
      mission_title: missionTitle.trim(),
      mission_context: `${opportunity.description} This proposal is bound to design-partner qualification ${qualification.partner_key}.`,
      stop_condition:
        "Stop before any scope expansion, missing approval, failed verification, production mutation, or authority ambiguity.",
      plan_summary:
        "Create a bounded Mission Control Mission and Plan draft. Mission Control retains review, approval, dispatch, verification, acceptance, merge, release, and deployment authority.",
      rollback_approach:
        "Revert only the bounded candidate change, restore the prior reviewed revision, and rerun independent verification before any new decision.",
      objective: objective.trim(),
      intent: `Prepare ${opportunity.name.toLowerCase()} for governed downstream planning without executing it.`,
      specification: buildDataMinimizedImplementationSpecification({
        model,
        opportunity,
        readiness,
        prerequisites,
        implementationSpecReference,
        repositoryRef,
        workflowClass,
        requestedCodeScopes,
      }),
      acceptance_criteria: acceptanceCriteria,
      constraints: [
        {
          key: "bounded-repository-scope",
          statement: `Work remains within ${repositoryRef} and the listed code scopes.`,
        },
        {
          key: "qualified-customer-context",
          statement:
            "No customer source, credential, or context outside the recorded qualification may be requested or used.",
        },
      ],
      required_capabilities: [
        {
          key: "bounded-software-change",
          statement:
            "Prepare and independently verify a scoped software change without expanding authority.",
        },
      ],
      required_agents: [],
      required_skills: [],
      required_tools: [],
      model_requirements: [],
      context_requirements: [
        {
          key: "approved-source-context",
          statement:
            "Use only version-pinned Factory Engineer sources resolved by Mission Control.",
        },
      ],
      environment_requirements: [
        {
          key: "isolated-non-production",
          statement:
            "Execute only in an isolated non-production environment selected by Mission Control policy.",
        },
      ],
      authority_boundaries: [
        {
          key: "draft-only-handoff",
          subject: "Factory Engineer",
          maximum_authority: "Propose a Mission and Plan draft only.",
          prohibited_actions: [
            "approve a Plan",
            "dispatch a WorkOrder",
            "accept a result",
            "merge",
            "release",
            "deploy",
          ],
        },
      ],
      policy_requirements: [
        {
          key: "mission-control-governance",
          statement:
            "Mission Control independently enforces planning, execution, verification, acceptance, and release policy.",
        },
      ],
      approval_requirements: [
        {
          key: "human-plan-approval",
          statement:
            "A locally authorized human must approve the Mission Control Plan before work is dispatched.",
        },
      ],
      verification_contract: [
        {
          key: "independent-suite",
          statement:
            "Mission Control runs independent checks on the exact subject revision.",
          evidence_required: [
            "subject-bound command",
            "exit status",
            "changed-file list",
            "test receipt",
          ],
          independent: true,
        },
      ],
      evaluation_requirements: [
        {
          key: "no-regression",
          statement:
            "Existing verified behavior remains green on the exact candidate revision.",
        },
      ],
      rollback_requirements: [
        {
          key: "revert-change-set",
          statement:
            "The bounded candidate can be reverted without expanding customer-data access.",
        },
      ],
      observability_requirements: [
        {
          key: "structured-results",
          statement:
            "Verification emits non-sensitive result codes and subject-bound evidence.",
        },
      ],
      economics_baseline: economics.outputs,
      risk_summary: [
        {
          key: "design-partner-only",
          statement: `This ${qualification.data_classification} package is qualified for one design-partner boundary, not general customer production.`,
        },
      ],
      evidence_refs: model.evidence_refs,
      decision_refs: [readinessRef],
      provenance,
      plan_assertions: [
        {
          assertion_id: "assertion-bounded-change",
          title: "The candidate satisfies the reviewed bounded intent",
          outcome:
            "The requested behavior is implemented inside the approved scope and passes independent verification.",
          verification_method: "TEST",
          pass_condition:
            "All required checks pass with zero changes outside the requested code scopes.",
          required_evidence:
            "Subject-bound commands, exit statuses, changed-file list, and verification report.",
          requires_independent_validation: true,
          waiver_allowed: false,
        },
      ],
      work_order_blueprints: [
        {
          key: "implement-bounded-change",
          title: "Implement and verify the selected factory-line change",
          outcome:
            "A reviewable candidate satisfies every package acceptance criterion without exceeding authority.",
          requirements: [
            "Implement the approved specification",
            "Preserve existing verified behavior",
          ],
          acceptance_criterion_refs: acceptanceCriteria.map((item) => item.key),
          constraints: [
            "bounded-repository-scope",
            "qualified-customer-context",
          ],
          requested_code_scopes: requestedCodeScopes,
          capability_requirement_refs: ["bounded-software-change"],
          verification_requirement_refs: ["independent-suite"],
          authority_boundary_refs: ["draft-only-handoff"],
          sequence: 1,
          execution_role: "WORKER",
          is_mutating: true,
          priority: 1,
          risk_level: "MEDIUM",
          required_approvals: ["human-plan-approval"],
          dependencies: [],
          assertion_ids: ["assertion-bounded-change"],
        },
      ],
    },
  };
}

function buildDataMinimizedImplementationSpecification({
  model,
  opportunity,
  readiness,
  prerequisites,
  implementationSpecReference,
  repositoryRef,
  workflowClass,
  requestedCodeScopes,
}: {
  model: CustomerFactoryModel;
  opportunity: FactoryOpportunity;
  readiness: FDLCReadinessAssessment;
  prerequisites: FactoryHandoffPrerequisites;
  implementationSpecReference: FactorySourceReference;
  repositoryRef: string;
  workflowClass: string;
  requestedCodeScopes: string[];
}): string {
  if (
    !prerequisites.current_workflow_ref ||
    !prerequisites.target_workflow_ref
  ) {
    throw new Error(
      "The approved current and target workflow references are unavailable.",
    );
  }

  return JSON.stringify(
    {
      schema_version: "fdlc.data-minimized-implementation-specification/v1",
      purpose:
        "Prepare one reviewable candidate inside the approved repository and code scopes; do not execute, approve, merge, release, or deploy from this package.",
      target: {
        repository_ref: repositoryRef,
        requested_code_scopes: requestedCodeScopes,
        semantic_execution_workflow_ref: workflowClass,
        environment_class: "ISOLATED_NON_PRODUCTION",
      },
      approved_design_basis: {
        customer_factory_model: {
          ref: `customer_factory_model:${model.id}`,
          version: model.version_number,
          sha256: model.content_digest,
        },
        selected_factory_opportunity: {
          ref: `factory_opportunity:${opportunity.id}`,
          version: opportunity.version_number,
          sha256: opportunity.content_digest,
        },
        fdlc_readiness: {
          ref: `fdlc_readiness:${readiness.id}`,
          version: readiness.version_number,
          sha256: readiness.content_digest,
        },
        current_workflow: approvedWorkflowReference(
          prerequisites.current_workflow_ref,
        ),
        target_workflow: approvedWorkflowReference(
          prerequisites.target_workflow_ref,
        ),
        implementation_specification: implementationSpecReference,
      },
      work: [
        {
          sequence: 1,
          action:
            "Resolve the immutable approved design references through authorized systems.",
          output: "A bounded implementation candidate for independent review.",
        },
        {
          sequence: 2,
          action:
            "Implement only within the exact repository and code scopes in this specification.",
          output: "A reviewable change set with no scope expansion.",
        },
        {
          sequence: 3,
          action:
            "Run subject-bound independent verification and preserve the result receipt.",
          output: "Verification evidence for a separate human decision.",
        },
      ],
      data_boundary: {
        customer_content_embedded: false,
        evidence_quotes_embedded: false,
        source_filenames_embedded: false,
        implementation_artifact_content_embedded: false,
        resolution_rule:
          "Authorized consumers resolve immutable references upstream; this projection carries no customer evidence or artifact body.",
      },
    },
    null,
    2,
  );
}

export function customerModelAuthorityReference(
  model: CustomerFactoryModel,
): FactorySourceReference {
  return {
    kind: "APPROVED_INPUT",
    ref: `customer_factory_model:${model.id}`,
    version: model.version_number,
    sha256: model.content_digest,
  };
}

function approvedWorkflowReference(reference: {
  id: string;
  version: number;
  digest: string;
}): FactorySourceReference {
  return {
    kind: "APPROVED_INPUT",
    ref: `workflow:${reference.id}`,
    version: reference.version,
    sha256: reference.digest,
  };
}

function readinessBasis(
  stage: FDLCReadinessStage["stage"],
  prerequisites: FactoryHandoffPrerequisites,
): FactorySourceReference[] {
  const verified = prerequisites.verified_claim_refs[0];
  const current = prerequisites.current_workflow_ref
    ? approvedWorkflowReference(prerequisites.current_workflow_ref)
    : null;
  const target = prerequisites.target_workflow_ref
    ? approvedWorkflowReference(prerequisites.target_workflow_ref)
    : null;
  const artifact = prerequisites.implementation_artifact_refs[0];
  const economics = prerequisites.economic_case_ref;
  const candidates: Record<
    FDLCReadinessStage["stage"],
    Array<FactorySourceReference | null | undefined>
  > = {
    DISCOVER: [verified],
    DESIGN: [current, target],
    ASSEMBLE: [artifact],
    VALIDATE: [artifact, verified],
    DEPLOY: [artifact, target],
    OPERATE: [artifact],
    IMPROVE: [economics, verified],
  };
  const basis = candidates[stage].filter(
    (reference): reference is FactorySourceReference => Boolean(reference),
  );
  if (basis.length === 0) {
    throw new Error(`${humanize(stage)} has no immutable readiness basis.`);
  }
  return basis;
}

function uniqueReferences(
  references: FactorySourceReference[],
): FactorySourceReference[] {
  return Array.from(
    new Map(
      references.map((reference) => [
        `${reference.kind}:${reference.ref}:${reference.version ?? "none"}:${reference.sha256}`,
        reference,
      ]),
    ).values(),
  );
}

export function humanize(value: string): string {
  return value
    .toLowerCase()
    .replaceAll("_", " ")
    .replace(/^./, (character) => character.toUpperCase());
}

function factoryKey(value: string): string {
  const key = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 160);
  return key || "factory-line";
}
