import type {
  Claim,
  Contradiction,
  CustomerFactoryModel,
  DeploymentPackage,
  DeliveryScorecard,
  EconomicCase,
  EconomicScenario,
  EconomicValue,
  Engagement,
  EngagementAssessment,
  EngagementDataLifecycle,
  EngagementDeletionReceipt,
  EngagementWorkspace,
  Evidence,
  FactoryHandoffWorkspace,
  FactoryOpportunity,
  FactorySourceReference,
  FDLCReadinessAssessment,
  FDLCReadinessStage,
  ImplementationArtifact,
  InternalAlphaScorecard,
  OperatingModel,
  PackageRetrievalEvent,
  Workflow,
  WorkflowStep,
  WorkflowWorkspace,
} from "./types";

const STORAGE_KEY = "ai-fde-hosted-demo-v3";
const NOW = "2026-08-30T20:00:00.000Z";
const OPERATOR_ID = "00000000-0000-4000-8000-000000000001";

type DemoEngagement = {
  engagement: Engagement;
  evidence: Evidence[];
  claims: Claim[];
  contradictions: Contradiction[];
  operatingModel: OperatingModel;
  workflows: WorkflowWorkspace;
  economics: EconomicCase | null;
  artifacts: ImplementationArtifact[];
  assessments: EngagementAssessment[];
  latestExport: EngagementDataLifecycle["latest_export"];
  customerModel: CustomerFactoryModel | null;
  opportunities: FactoryOpportunity[];
  readiness: FDLCReadinessAssessment | null;
  deploymentPackages: DeploymentPackage[];
  retrievalEvents: PackageRetrievalEvent[];
};

type DemoState = {
  version: 3;
  engagements: Record<string, DemoEngagement>;
};

type Profile = {
  id: string;
  slug: string;
  company: string;
  workflow: string;
  outcome: string;
  accepted: string[];
  rejected: string[];
  contradiction?: string;
};

const PROFILES: Profile[] = [
  {
    id: "df1c4048-ddfb-4518-bb91-9db5e528ea26",
    slug: "acme-manufacturing",
    company: "Acme Manufacturing",
    workflow: "Accounts Payable",
    outcome:
      "Reduce invoice-processing cycle time while preserving financial approval controls.",
    accepted: [
      "Exception: Strategic vendors with an approved annual contract may be approved by Controller.",
      "Sarah Jones owns Accounts Payable.",
      "Invoices over $50,000 require CFO approval.",
      "Accounts Payable uses NetSuite.",
    ],
    rejected: [
      "Sarah Jones is identified as a person.",
      "Invoice approval is identified as a process.",
    ],
    contradiction:
      "Approval evidence names both CFO and Controller. Confirm whether this is a conflict, exception, or change over time.",
  },
  {
    id: "21427e57-fbf9-4521-91a2-9529187480c9",
    slug: "northstar-health",
    company: "Northstar Health",
    workflow: "Employee Access Onboarding",
    outcome:
      "Shorten new-hire access lead time while preserving privileged-access approval and the People Operations to IT handoff.",
    accepted: [
      "Priya Shah owns Employee Access Onboarding.",
      "Employee Access Onboarding uses Workday.",
      "Identity record creation precedes Account provisioning.",
      "Requests for privileged systems require Security approval.",
      "People Operations hands off to IT Service Desk.",
      "Account Provisioning uses Okta.",
    ],
    rejected: [
      "Employee Access Onboarding is identified as a process.",
      "Priya Shah is identified as a person.",
      "Security is identified as a role.",
      "Workday is identified as a system.",
      "People Operations is identified as a role.",
      "IT Service Desk is identified as a role.",
      "Okta is identified as a system.",
    ],
  },
  {
    id: "b4c1d7f5-52f4-43d1-a429-325f15d4ef6a",
    slug: "beacon-logistics",
    company: "Beacon Logistics",
    workflow: "Customer Support Triage",
    outcome:
      "Reduce support-routing time while preserving Zendesk as the system of record and the Service Response Policy.",
    accepted: [
      "Jordan Lee owns Customer Support Triage.",
      "Customer Support Triage uses Zendesk.",
      "Classify inbound request precedes Route standard request.",
      "Customer Support Triage is governed by Service Response Policy.",
    ],
    rejected: [
      "Customer Support Triage is identified as a process.",
      "Jordan Lee is identified as a person.",
      "Zendesk is identified as a system.",
    ],
  },
];

export const hostedDemoEnabled =
  process.env.NEXT_PUBLIC_AI_FDE_HOSTED_DEMO === "true";

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function claimFor(profile: Profile, summary: string, index: number): Claim {
  const isEntity = summary.includes("is identified as");
  const evidenceId = `${profile.id.slice(0, 8)}-0000-4000-8000-${String(index + 1).padStart(12, "0")}`;
  return {
    id: `${profile.id.slice(0, 8)}-1000-4000-8000-${String(index + 1).padStart(12, "0")}`,
    claim_kind: isEntity
      ? "entity"
      : summary.startsWith("Exception:")
        ? "exception"
        : summary.includes("require") || summary.includes("governed")
          ? "rule"
          : "relationship",
    subject_text: summary.split(" ")[0],
    predicate: predicateFor(summary),
    object_text: summary,
    summary,
    normalized_payload: { synthetic: true },
    confidence: "0.94",
    materiality: isEntity ? "low" : "material",
    status: "candidate",
    created_at: NOW,
    provenance: [
      {
        claim_evidence_id: evidenceId,
        evidence_segment_id: evidenceId,
        evidence_asset_id: evidenceId,
        file_name: `${profile.slug}-evidence.md`,
        source_type: "fixture",
        source_timestamp: null,
        locator: { start: 0, line: index + 1 },
        quote: summary,
        start_offset: 0,
        end_offset: summary.length,
      },
    ],
  };
}

function predicateFor(summary: string): Claim["predicate"] {
  if (summary.includes("is identified as")) return "IDENTIFIED_AS";
  if (summary.includes(" owns ")) return "OWNS";
  if (summary.includes(" uses ")) return "USES";
  if (summary.includes(" require") || summary.includes("approved by"))
    return "REQUIRES_APPROVAL";
  if (summary.includes(" precedes ")) return "PRECEDES";
  if (summary.includes(" hands off to ")) return "HANDS_OFF_TO";
  return "GOVERNED_BY";
}

function seedEngagement(profile: Profile): DemoEngagement {
  const summaries = [...profile.accepted, ...profile.rejected];
  const claims = summaries.map((summary, index) =>
    claimFor(profile, summary, index),
  );
  const evidenceId = `${profile.id.slice(0, 8)}-0000-4000-8000-000000000001`;
  const engagement: Engagement = {
    id: profile.id,
    name: profile.company,
    slug: profile.slug,
    workflow_name: profile.workflow,
    primary_outcome: profile.outcome,
    lifecycle_stage: "discover",
    data_classification: "synthetic",
    data_lifecycle_status: "active",
    retention_expires_at: null,
    created_at: NOW,
    updated_at: NOW,
  };
  return {
    engagement,
    evidence: [
      {
        id: evidenceId,
        engagement_id: profile.id,
        file_name: `${profile.slug}-evidence.md`,
        content_type: "text/markdown",
        content_hash: "f".repeat(64),
        byte_count: summaries.join("\n").length,
        source_type: "fixture",
        source_timestamp: null,
        status: "needs_review",
        error_message: null,
        created_at: NOW,
      },
    ],
    claims,
    contradictions: profile.contradiction
      ? [
          {
            id: `${profile.id.slice(0, 8)}-2000-4000-8000-000000000001`,
            summary: profile.contradiction,
            status: "open",
            blocking: true,
            left_claim_id: claims[0].id,
            right_claim_id: claims[2].id,
            resolution_type: null,
            resolution_reason: null,
            resolved_by_id: null,
            resolved_at: null,
            created_at: NOW,
          },
        ]
      : [],
    operatingModel: { entities: [], assertions: [] },
    workflows: { current: null, target: null },
    economics: null,
    artifacts: [],
    assessments: [],
    latestExport: null,
    customerModel: null,
    opportunities: [],
    readiness: null,
    deploymentPackages: [],
    retrievalEvents: [],
  };
}

function initialState(): DemoState {
  return {
    version: 3,
    engagements: Object.fromEntries(
      PROFILES.map((profile) => [profile.id, seedEngagement(profile)]),
    ),
  };
}

function readState(): DemoState {
  if (typeof window === "undefined") return initialState();
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (!stored) {
    const state = initialState();
    writeState(state);
    return state;
  }
  try {
    const state = JSON.parse(stored) as DemoState;
    if (state.version === 3) return state;
  } catch {
    // Replace malformed or obsolete demo state with the deterministic seed.
  }
  const state = initialState();
  writeState(state);
  return state;
}

function writeState(state: DemoState) {
  if (typeof window !== "undefined") {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }
}

function requireEngagement(state: DemoState, engagementId: string) {
  const found = state.engagements[engagementId];
  if (!found) throw new Error("The synthetic engagement was not found.");
  return found;
}

function requestBody<T>(init?: RequestInit): T {
  if (typeof init?.body !== "string") return {} as T;
  return JSON.parse(init.body) as T;
}

function acceptedMaterialClaims(item: DemoEngagement) {
  return item.claims.filter(
    (claim) => claim.status === "accepted" && claim.materiality === "material",
  );
}

function workspace(item: DemoEngagement): EngagementWorkspace {
  return {
    engagement: item.engagement,
    counts: {
      evidence: item.evidence.length,
      candidate_claims: item.claims.filter(
        (claim) => claim.status === "candidate",
      ).length,
      verified_assertions: item.operatingModel.assertions.length,
    },
  };
}

const FACTORY_OPPORTUNITY_FIXTURES = {
  "acme-manufacturing": {
    opportunity_key: "dependency-modernization",
    name: "Dependency modernization",
    description:
      "Modernize the synthetic invoice integration dependencies within a bounded repository scope and deterministic compatibility suite.",
    factors: {
      workflow_frequency: 4,
      human_effort: 3,
      cycle_time: 3,
      repeatability: 5,
      standardization: 5,
      evidence_quality: 4,
      deterministic_verifiability: 5,
      blast_radius: 3,
      system_accessibility: 4,
      data_sensitivity: 2,
      implementation_complexity: 3,
      expected_economic_value: 4,
      autonomy_potential: 4,
    },
  },
  "northstar-health": {
    opportunity_key: "security-remediation",
    name: "Security remediation",
    description:
      "Remediate bounded identity-policy findings with independent validation and retained human approval authority.",
    factors: {
      workflow_frequency: 4,
      human_effort: 4,
      cycle_time: 4,
      repeatability: 4,
      standardization: 5,
      evidence_quality: 5,
      deterministic_verifiability: 4,
      blast_radius: 5,
      system_accessibility: 3,
      data_sensitivity: 5,
      implementation_complexity: 4,
      expected_economic_value: 5,
      autonomy_potential: 2,
    },
  },
  "beacon-logistics": {
    opportunity_key: "test-remediation",
    name: "Test remediation",
    description:
      "Repair deterministic routing regressions while preserving Zendesk as the synthetic system of record.",
    factors: {
      workflow_frequency: 5,
      human_effort: 4,
      cycle_time: 4,
      repeatability: 5,
      standardization: 4,
      evidence_quality: 4,
      deterministic_verifiability: 5,
      blast_radius: 2,
      system_accessibility: 5,
      data_sensitivity: 2,
      implementation_complexity: 2,
      expected_economic_value: 4,
      autonomy_potential: 5,
    },
  },
} as const;

const OPPORTUNITY_RUBRIC = {
  value: {
    workflow_frequency: 25,
    human_effort: 25,
    cycle_time: 20,
    expected_economic_value: 30,
  },
  verifiability: {
    repeatability: 25,
    standardization: 20,
    evidence_quality: 25,
    deterministic_verifiability: 30,
  },
  readiness: {
    system_accessibility: 30,
    evidence_quality: 25,
    standardization: 20,
    inverse_implementation_complexity: 25,
  },
  risk: {
    blast_radius: 40,
    data_sensitivity: 35,
    implementation_complexity: 25,
  },
  autonomy: {
    autonomy_potential: 35,
    repeatability: 20,
    deterministic_verifiability: 25,
    inverse_blast_radius: 20,
  },
  priority: {
    value: 30,
    verifiability: 25,
    readiness: 20,
    autonomy: 15,
    inverse_risk: 10,
  },
} as const;

function weightedFactorScore(
  values: Record<string, number>,
  weights: Record<string, number>,
) {
  const weighted = Object.entries(weights).reduce(
    (sum, [key, weight]) => sum + values[key] * weight,
    0,
  );
  const denominator =
    5 * Object.values(weights).reduce((sum, value) => sum + value, 0);
  return Math.floor((weighted * 100 + denominator / 2) / denominator);
}

function weightedPercentageScore(
  values: Record<string, number>,
  weights: Record<string, number>,
) {
  const weighted = Object.entries(weights).reduce(
    (sum, [key, weight]) => sum + values[key] * weight,
    0,
  );
  const denominator = Object.values(weights).reduce(
    (sum, value) => sum + value,
    0,
  );
  return Math.floor((weighted + denominator / 2) / denominator);
}

function canonicalSyntheticValue(value: unknown): unknown {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "boolean"
  ) {
    return value;
  }
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value)) {
      throw new Error(
        "Synthetic integrity payloads permit only cross-language safe integers.",
      );
    }
    return value;
  }
  if (Array.isArray(value)) {
    return value.map((item) => canonicalSyntheticValue(item));
  }
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    const canonical: Record<string, unknown> = {};
    for (const key of Object.keys(record).sort()) {
      if (![...key].every((character) => character.charCodeAt(0) <= 0x7f)) {
        throw new Error("Synthetic integrity payload keys must be ASCII.");
      }
      if (record[key] !== undefined) {
        canonical[key] = canonicalSyntheticValue(record[key]);
      }
    }
    return canonical;
  }
  throw new Error("Synthetic integrity payload contains an unsupported value.");
}

async function syntheticSha256(value: unknown) {
  const bytes = new TextEncoder().encode(
    JSON.stringify(canonicalSyntheticValue(value)),
  );
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return `sha256:${Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("")}`;
}

async function syntheticPackageDigest(deploymentPackage: DeploymentPackage) {
  if (!deploymentPackage.approval || !deploymentPackage.issued_at) {
    throw new Error("Synthetic package approval binding is incomplete.");
  }
  return syntheticSha256({
    schema_version: deploymentPackage.schema_version,
    package_id: deploymentPackage.package_id,
    package_version: deploymentPackage.package_version,
    status: "PUBLISHED",
    issuer: deploymentPackage.issuer,
    issued_at: deploymentPackage.issued_at,
    approval: deploymentPackage.approval,
    integrity: {
      canonicalization: "fdlc-canonical-json/v1",
      algorithm: "sha256",
    },
    source: {
      engagement_id: deploymentPackage.engagement_id,
      ...deploymentPackage.source,
    },
    target: deploymentPackage.target,
    deployment_intent: deploymentPackage.deployment_intent,
  });
}

async function buildSyntheticCustomerModel(
  item: DemoEngagement,
): Promise<CustomerFactoryModel> {
  if (
    item.claims.some((claim) => claim.status === "candidate") ||
    item.contradictions.some((contradiction) => contradiction.blocking) ||
    item.operatingModel.assertions.length === 0
  ) {
    throw new Error(
      "Complete claim review and resolve material contradictions before approving the customer model.",
    );
  }
  const evidenceRefs = item.evidence.map((evidence) => ({
    kind: "EVIDENCE" as const,
    ref: `evidence_asset:${evidence.id}`,
    version: null,
    sha256: `sha256:${evidence.content_hash}`,
  }));
  const verifiedClaimRefs = await Promise.all(
    item.operatingModel.assertions.map(async (assertion) => ({
      kind: "VERIFIED_CLAIM" as const,
      ref: `assertion:${assertion.id}`,
      version: 1,
      sha256: await syntheticSha256(assertion),
    })),
  );
  const provenance = [verifiedClaimRefs[0], evidenceRefs[0]];
  const modelPayload: Omit<
    CustomerFactoryModel,
    | "id"
    | "engagement_id"
    | "version_number"
    | "status"
    | "content_digest"
    | "approved_at"
    | "stale_reason"
    | "created_at"
  > = {
    organization: {
      key: item.engagement.slug,
      label: item.engagement.name,
      description: `Synthetic customer factory model for ${item.engagement.workflow_name}.`,
      provenance_refs: provenance,
      attributes: { data_classification: "synthetic" },
    },
    workflows: [
      {
        key: item.engagement.workflow_name.toLowerCase().replaceAll(" ", "-"),
        label: item.engagement.workflow_name,
        description: item.engagement.primary_outcome,
        provenance_refs: provenance,
        attributes: { source: "approved-workflow" },
      },
    ],
    systems: [],
    repositories: [],
    environments: [],
    policies: [],
    authority_boundaries: [
      {
        key: "engagement-owner-publication",
        label: "Engagement owner publication authority",
        description:
          "Only the authenticated human engagement owner may approve and publish deployment intent.",
        provenance_refs: provenance,
        attributes: { maximum_authority: "DEPLOYMENT_PACKAGE_PUBLISH" },
      },
    ],
    constraints: [],
    risks: [],
    baselines: [],
    evidence_refs: evidenceRefs,
    verified_claim_refs: verifiedClaimRefs,
    assumption_refs: [],
    factory_opportunity_refs: [],
  };
  return {
    id: crypto.randomUUID(),
    engagement_id: item.engagement.id,
    version_number: 1,
    status: "APPROVED",
    ...modelPayload,
    content_digest: await syntheticSha256(modelPayload),
    approved_at: NOW,
    stale_reason: null,
    created_at: NOW,
  };
}

async function buildSyntheticOpportunity(
  item: DemoEngagement,
): Promise<FactoryOpportunity> {
  if (!item.customerModel || !item.workflows.current || !item.economics) {
    throw new Error(
      "Approve the customer model, current workflow, and baseline economics before assessing opportunities.",
    );
  }
  const fixture =
    FACTORY_OPPORTUNITY_FIXTURES[
      item.engagement.slug as keyof typeof FACTORY_OPPORTUNITY_FIXTURES
    ];
  if (!fixture)
    throw new Error("No synthetic opportunity fixture is configured.");
  const factors = { ...fixture.factors } as Record<string, number>;
  const expanded = {
    ...factors,
    inverse_implementation_complexity: 5 - factors.implementation_complexity,
    inverse_blast_radius: 5 - factors.blast_radius,
  };
  const value = weightedFactorScore(expanded, OPPORTUNITY_RUBRIC.value);
  const verifiability = weightedFactorScore(
    expanded,
    OPPORTUNITY_RUBRIC.verifiability,
  );
  const readiness = weightedFactorScore(expanded, OPPORTUNITY_RUBRIC.readiness);
  const risk = weightedFactorScore(expanded, OPPORTUNITY_RUBRIC.risk);
  const autonomy = weightedFactorScore(expanded, OPPORTUNITY_RUBRIC.autonomy);
  const priority = weightedPercentageScore(
    {
      value,
      verifiability,
      readiness,
      autonomy,
      inverse_risk: 100 - risk,
    },
    OPPORTUNITY_RUBRIC.priority,
  );
  const payload = {
    fixture,
    value,
    verifiability,
    readiness,
    risk,
    autonomy,
    priority,
  };
  const economicsRef: FactorySourceReference = {
    kind: "APPROVED_INPUT",
    ref: `economic_case:${item.economics.id}`,
    version: item.economics.version_number,
    sha256: await syntheticSha256(item.economics),
  };
  return {
    id: crypto.randomUUID(),
    engagement_id: item.engagement.id,
    opportunity_key: fixture.opportunity_key,
    version_number: 1,
    status: priority >= 75 && risk <= 60 ? "RECOMMENDED" : "ASSESSED",
    name: fixture.name,
    description: fixture.description,
    source_workflow_ref: {
      id: item.workflows.current.id,
      version: item.workflows.current.version_number,
      digest: await syntheticSha256(item.workflows.current),
    },
    customer_factory_model_id: item.customerModel.id,
    customer_factory_model_version: item.customerModel.version_number,
    value_score: value,
    verifiability_score: verifiability,
    readiness_score: readiness,
    risk_score: risk,
    autonomy_potential: autonomy,
    priority_score: priority,
    factors,
    rubric: clone(OPPORTUNITY_RUBRIC),
    rubric_version: "factory-opportunity-rubric/v1",
    economics_ref: economicsRef,
    evidence_refs: clone(item.customerModel.evidence_refs),
    rationale: [
      `Value ${value}/100 from frequency, effort, cycle time, and expected economics.`,
      `Verifiability ${verifiability}/100 from repeatability, standards, evidence, and deterministic checks.`,
      `Readiness ${readiness}/100 after system access and implementation complexity.`,
      `Risk ${risk}/100 from blast radius, data sensitivity, and implementation complexity.`,
      `Priority ${priority}/100 using the published factory-opportunity-rubric/v1 weights.`,
    ],
    blockers: [],
    recommendation:
      priority >= 75 && risk <= 60
        ? "RECOMMEND — strong value, verification, and readiness fit."
        : "ASSESS — viable candidate with material tradeoffs to resolve.",
    content_digest: await syntheticSha256(payload),
    selection_reason: null,
    selected_at: null,
    rejection_reason: null,
    rejected_at: null,
    stale_reason: null,
    created_at: NOW,
  };
}

const READINESS_STAGE_LABELS: Array<FDLCReadinessStage["stage"]> = [
  "DISCOVER",
  "DESIGN",
  "ASSEMBLE",
  "VALIDATE",
  "DEPLOY",
  "OPERATE",
  "IMPROVE",
];

const SYNTHETIC_READINESS_CRITERIA: Record<
  FDLCReadinessStage["stage"],
  string[]
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

async function buildSyntheticReadiness(
  item: DemoEngagement,
): Promise<FDLCReadinessAssessment> {
  const selected = item.opportunities.find(
    (opportunity) => opportunity.status === "SELECTED",
  );
  const packetCurrent = item.artifacts.length === 7;
  if (
    !selected ||
    item.workflows.target?.status !== "approved" ||
    item.economics?.status !== "approved" ||
    !packetCurrent
  ) {
    throw new Error(
      "Select a factory line and approve the target workflow, economics, and implementation packet before final readiness.",
    );
  }
  const customerModel = item.customerModel;
  const basis = customerModel?.verified_claim_refs[0];
  if (!customerModel || !basis)
    throw new Error("The approved customer model has no verified basis.");
  const stages = READINESS_STAGE_LABELS.map((stage) => ({
    stage,
    status: "READY" as const,
    score: 100,
    evidence_refs: [basis],
    blockers: [],
    risks:
      stage === "DEPLOY"
        ? [
            "Synthetic proof only; production credentials and target remain disabled.",
          ]
        : [],
    decisions: [basis],
    required_artifacts:
      stage === "VALIDATE"
        ? ["verification strategy", "rollback plan"]
        : stage === "DEPLOY"
          ? ["factory deployment package"]
          : [],
    owner: "Hosted Demo FDE",
    next_actions: [],
    criteria: SYNTHETIC_READINESS_CRITERIA[stage].map((criterion) => ({
      key: criterion,
      label: criterion.replaceAll("_", " "),
      satisfied: true,
      blocking: true,
      explanation:
        "The hosted rehearsal has an explicit immutable synthetic basis.",
      basis_refs: [basis],
      next_action: null,
    })),
    explanation: "Every required criterion is satisfied with a recorded basis.",
    updated_at: NOW,
  }));
  const currentWorkflowRef = selected.source_workflow_ref;
  const targetWorkflowRef = {
    id: item.workflows.target.id,
    version: item.workflows.target.version_number,
    digest: await syntheticSha256(item.workflows.target),
  };
  const payload = {
    selected_opportunity_id: selected.id,
    current_workflow_ref: currentWorkflowRef,
    target_workflow_ref: targetWorkflowRef,
    stages,
  };
  return {
    id: crypto.randomUUID(),
    engagement_id: item.engagement.id,
    version_number: 1,
    status: "DRAFT",
    overall_status: "READY",
    customer_factory_model_id: customerModel.id,
    customer_factory_model_version: customerModel.version_number,
    selected_opportunity_id: selected.id,
    selected_opportunity_version: selected.version_number,
    current_workflow_ref: currentWorkflowRef,
    target_workflow_ref: targetWorkflowRef,
    stages,
    content_digest: await syntheticSha256(payload),
    approved_at: null,
    stale_reason: null,
    created_at: NOW,
  };
}

async function buildSyntheticPackage(
  item: DemoEngagement,
): Promise<DeploymentPackage> {
  const selected = item.opportunities.find(
    (opportunity) => opportunity.status === "SELECTED",
  );
  if (
    !item.customerModel ||
    !selected ||
    item.readiness?.status !== "APPROVED" ||
    !item.workflows.current ||
    !item.workflows.target
  ) {
    throw new Error(
      "Approved final readiness is required before package generation.",
    );
  }
  const requestedCodeScopes = ["apps/synthetic-target/**"];
  const readinessDecisionRef: FactorySourceReference = {
    kind: "APPROVED_INPUT",
    ref: `fdlc_readiness:${item.readiness.id}`,
    version: item.readiness.version_number,
    sha256: item.readiness.content_digest,
  };
  const intent: DeploymentPackage["deployment_intent"] = {
    mission_title: `${selected.name} · ${item.engagement.name}`,
    mission_context: `Implement the selected ${selected.name.toLowerCase()} line from approved synthetic customer truth.`,
    stop_condition:
      "Stop when any non-waivable authority, verification, or repository-scope gate cannot be satisfied.",
    plan_summary:
      "Create a bounded Mission Control Plan draft; retain downstream review, approval, verification, and release authority in Mission Control.",
    rollback_approach:
      "Restore the prior dependency and lockfile state, then rerun the deterministic verification suite.",
    objective: item.engagement.primary_outcome,
    intent: `Prepare ${selected.name.toLowerCase()} for governed Mission Control planning.`,
    specification: item.artifacts.find(
      (artifact) => artifact.artifact_type === "implementation_spec",
    )!.content,
    acceptance_criteria: [
      {
        key: "bounded-change",
        statement: "Changes remain inside the approved repository scope.",
        verification_method: "CHECKLIST",
      },
      {
        key: "verification-green",
        statement:
          "The deterministic validation suite passes on the exact result.",
        verification_method: "TEST",
      },
    ],
    constraints: [
      {
        key: "bounded-repository-scope",
        statement:
          "Changes remain inside the exact code scope selected by the human operator.",
      },
    ],
    required_capabilities: [
      {
        key: "bounded-software-change",
        statement:
          "Implement and verify a scoped software change without expanding authority.",
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
          "Use only the approved, version-pinned intent and repository state resolved by Mission Control.",
      },
    ],
    environment_requirements: [
      {
        key: "isolated-non-production",
        statement:
          "Run only in an isolated non-production environment chosen by Mission Control policy.",
      },
    ],
    authority_boundaries: [
      {
        key: "draft-only-handoff",
        subject: "Factory Engineer",
        maximum_authority: "Propose Mission and Plan drafts only.",
        prohibited_actions: [
          "approve Plan",
          "dispatch WorkOrder",
          "accept result",
          "merge or deploy",
        ],
      },
    ],
    policy_requirements: [
      {
        key: "mission-control-governance",
        statement:
          "Mission Control must independently authorize planning, execution, verification, acceptance, and release.",
      },
    ],
    approval_requirements: [
      {
        key: "human-plan-approval",
        statement:
          "A locally authorized human must approve the Mission Control Plan before WorkOrders are created.",
      },
    ],
    verification_contract: [
      {
        key: "independent-suite",
        statement:
          "Mission Control runs independent checks on the exact subject revision.",
        evidence_required: ["test receipt bound to subject revision"],
        independent: true,
      },
    ],
    evaluation_requirements: [
      {
        key: "no-regression",
        statement:
          "Existing behavior remains green on the exact candidate revision.",
      },
    ],
    rollback_requirements: [
      {
        key: "revert-change-set",
        statement:
          "The bounded change can be reverted without a production data migration.",
      },
    ],
    observability_requirements: [
      {
        key: "structured-results",
        statement:
          "Verification emits structured, non-sensitive result codes and subject-bound evidence.",
      },
    ],
    risk_summary: [
      {
        key: "synthetic-only",
        statement:
          "This hosted package is synthetic and cannot authorize production work.",
      },
    ],
    economics_baseline: clone(item.economics?.outputs ?? {}),
    evidence_refs: clone(item.customerModel.evidence_refs),
    decision_refs: [readinessDecisionRef],
    provenance: [
      ...clone(item.customerModel.evidence_refs),
      ...clone(item.customerModel.verified_claim_refs),
    ],
    plan_assertions: [
      {
        assertion_id: "assertion-bounded-change",
        title: "The scoped change satisfies the approved intent",
        outcome:
          "The requested behavior is implemented inside the approved scope and passes deterministic verification.",
        verification_method: "TEST",
        pass_condition:
          "All focused tests pass with zero changes outside the requested code scope.",
        required_evidence:
          "Subject-bound command, exit status, changed-file list, and test report.",
        requires_independent_validation: true,
        waiver_allowed: false,
      },
    ],
    work_order_blueprints: [
      {
        key: "implement-bounded-change",
        title: "Implement and verify the selected factory-line change",
        outcome:
          "A reviewable candidate satisfies both package acceptance criteria without exceeding its authority.",
        requirements: [
          "Implement the approved specification",
          "Preserve existing verified behavior",
        ],
        acceptance_criterion_refs: ["bounded-change", "verification-green"],
        constraints: ["bounded-repository-scope"],
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
  };
  const source = {
    customer_factory_model: {
      id: item.customerModel.id,
      version: item.customerModel.version_number,
      digest: item.customerModel.content_digest,
    },
    current_workflow: {
      id: item.workflows.current.id,
      version: item.workflows.current.version_number,
      digest: await syntheticSha256(item.workflows.current),
    },
    target_workflow: {
      id: item.workflows.target.id,
      version: item.workflows.target.version_number,
      digest: await syntheticSha256(item.workflows.target),
    },
    readiness_assessment: {
      id: item.readiness.id,
      version: item.readiness.version_number,
      digest: item.readiness.content_digest,
    },
    factory_opportunity: {
      id: selected.id,
      version: selected.version_number,
      digest: selected.content_digest,
    },
  };
  const target = {
    workspace_ref: "mission-control://workspace/synthetic-demo",
    repository_ref: "github.com/jaydubya818/synthetic-factory-target",
    requested_code_scopes: requestedCodeScopes,
    semantic_execution_workflow_ref: "software-change/default",
    environment_class: "ISOLATED_NON_PRODUCTION",
  };
  const packageId = crypto.randomUUID();
  return {
    id: crypto.randomUUID(),
    engagement_id: item.engagement.id,
    package_id: packageId,
    package_version: 1,
    schema_version: "fdlc.factory-deployment-package/v1",
    status: "DRAFT",
    issuer: {
      issuer_id: "factory-engineer-hosted-demo",
      issuer_type: "FDLC_FACTORY_ENGINEER",
      environment: "development",
      authority_scope: "DEPLOYMENT_PACKAGE_PUBLISH",
    },
    source,
    target,
    deployment_intent: intent,
    digest: null,
    approval: null,
    issued_at: null,
    approved_at: null,
    published_at: null,
    state_reason: null,
    created_at: NOW,
  };
}

function buildSteps(item: DemoEngagement): WorkflowStep[] {
  const workflow = item.engagement.workflow_name;
  if (workflow === "Accounts Payable") {
    return [
      step(item, 1, "Approve over $50,000", "CFO", null, "human"),
      step(
        item,
        2,
        "Process work in NetSuite",
        "Sarah Jones",
        "NetSuite",
        "software",
      ),
      step(
        item,
        3,
        "Handle strategic vendor exception",
        "Controller",
        null,
        "human",
      ),
    ];
  }
  if (workflow === "Employee Access Onboarding") {
    return [
      step(
        item,
        1,
        "Create identity record",
        "People Operations",
        "Workday",
        "software",
      ),
      step(item, 2, "Provision account", "IT Service Desk", "Okta", "software"),
      step(item, 3, "Approve privileged access", "Security", null, "human"),
    ];
  }
  return [
    step(
      item,
      1,
      "Classify inbound request",
      "Support Operations",
      "Zendesk",
      "ai_human",
    ),
    step(
      item,
      2,
      "Route standard request",
      "Support Operations",
      "Zendesk",
      "software",
    ),
    step(item, 3, "Apply Service Response Policy", "Jordan Lee", null, "human"),
  ];
}

function step(
  item: DemoEngagement,
  position: number,
  name: string,
  actor: string,
  system: string | null,
  allocation: WorkflowStep["allocation"],
): WorkflowStep {
  return {
    id: `${item.engagement.id.slice(0, 8)}-3000-4000-8000-${String(position).padStart(12, "0")}`,
    step_key: `step-${position}`,
    position,
    name,
    description: `Evidence-backed ${name.toLowerCase()} step for the synthetic hosted demonstration.`,
    step_type: allocation === "human" ? "human_task" : "software_task",
    actor_label: actor,
    system_label: system,
    allocation,
    rationale:
      allocation === "human"
        ? "Retain material approval authority with a human operator."
        : "Use deterministic software for the bounded system action.",
    controls: ["Human review", "Audit event"],
    source_assertion_id: item.operatingModel.assertions[0]?.id ?? null,
  };
}

function createWorkflow(
  item: DemoEngagement,
  kind: Workflow["workflow_kind"],
): Workflow {
  const source = kind === "target" ? item.workflows.current : null;
  return {
    id: `${item.engagement.id.slice(0, 8)}-${kind === "current" ? "4000" : "5000"}-4000-8000-000000000001`,
    workflow_kind: kind,
    version_number: 1,
    name: `${item.engagement.workflow_name} — ${kind === "current" ? "Current" : "Target"} State`,
    objective: item.engagement.primary_outcome,
    status: "draft",
    source_workflow_id: source?.id ?? null,
    source_assertion_ids: item.operatingModel.assertions.map(
      (assertion) => assertion.id,
    ),
    generated_by: "system",
    approved_at: null,
    approval_reason: null,
    created_at: NOW,
    updated_at: NOW,
    steps: source ? clone(source.steps) : buildSteps(item),
  };
}

function economicValue(
  value: string | null,
  unit: string,
  formula?: string,
): EconomicValue {
  return { value, unit, classification: "calculated", formula };
}

function scenario(
  label: string,
  description: string,
  net: string,
  payback: string,
): EconomicScenario {
  return {
    label,
    description,
    inputs: {},
    outputs: {
      annual_net_benefit: economicValue(net, "USD / year"),
      payback_months: economicValue(payback, "months"),
    },
  };
}

function buildEconomics(
  item: DemoEngagement,
  payload: Record<
    string,
    { value: string; classification: EconomicValue["classification"] }
  >,
): EconomicCase {
  const inputs = Object.fromEntries(
    Object.entries(payload)
      .filter(([, value]) => typeof value === "object" && "value" in value)
      .map(([key, value]) => [
        key,
        {
          value: value.value,
          unit: key.includes("cost") ? "USD" : "synthetic input",
          classification: value.classification,
        },
      ]),
  );
  return {
    id: `${item.engagement.id.slice(0, 8)}-6000-4000-8000-000000000001`,
    version_number: 1,
    status: "draft",
    source_target_workflow_id: item.workflows.target!.id,
    formula_version: "hosted-demo-v1",
    inputs,
    outputs: {
      annual_hours_saved: economicValue(
        "4000",
        "hours / year",
        "annual_volume × (current_minutes_per_item − target_minutes_per_item) ÷ 60",
      ),
      annual_gross_labor_value: economicValue(
        "168000",
        "USD / year",
        "annual_hours_saved × loaded_hourly_cost",
      ),
      annual_net_benefit: economicValue(
        "150000",
        "USD / year",
        "annual_gross_labor_value − annual_operating_cost",
      ),
      payback_months: economicValue(
        "6.8",
        "months",
        "implementation_cost ÷ annual_net_benefit × 12",
      ),
    },
    scenarios: {
      low: scenario(
        "Low",
        "Conservative volume, adoption, and time-savings assumptions.",
        "72000",
        "14.2",
      ),
      base: scenario(
        "Base",
        "Version-pinned synthetic assumptions entered by the operator.",
        "150000",
        "6.8",
      ),
      high: scenario(
        "High",
        "Higher adoption and captured time savings, still synthetic.",
        "238000",
        "4.3",
      ),
    },
    assumptions: [
      "Synthetic hosted-demo inputs only; replace before customer use.",
    ],
    approved_at: null,
    created_at: NOW,
    updated_at: NOW,
  };
}

const ARTIFACT_TYPES: ImplementationArtifact["artifact_type"][] = [
  "prd",
  "architecture",
  "business_rules",
  "integration_requirements",
  "approval_controls",
  "evaluation_plan",
  "implementation_spec",
];

function buildArtifacts(item: DemoEngagement): ImplementationArtifact[] {
  const accepted = acceptedMaterialClaims(item)
    .map((claim) => `- ${claim.summary}`)
    .join("\n");
  return ARTIFACT_TYPES.map((type, index) => ({
    id: `${item.engagement.id.slice(0, 8)}-7000-4000-8000-${String(index + 1).padStart(12, "0")}`,
    artifact_type: type,
    packet_version: 1,
    version_number: 1,
    status: "current",
    title: `${item.engagement.workflow_name} — ${type.replaceAll("_", " ")}`,
    content: `# ${item.engagement.workflow_name} — ${type.replaceAll("_", " ")}\n\n## Version pins\n\n- Current workflow: ${item.workflows.current!.id}\n- Target workflow: ${item.workflows.target!.id}\n- Economic case: ${item.economics!.id}\n\n## Verified implementation intent\n\n${accepted}\n\n## Acceptance criteria\n\n- Preserve evidence provenance and human approval boundaries.\n- Reproduce annual_net_benefit from stored assumptions.\n- No production deployment or autonomous remediation is authorized by this synthetic packet.\n`,
    content_hash: String(index + 1)
      .repeat(64)
      .slice(0, 64),
    source_current_workflow_id: item.workflows.current!.id,
    source_target_workflow_id: item.workflows.target!.id,
    economic_case_id: item.economics!.id,
    source_assertion_ids: item.operatingModel.assertions.map(
      (assertion) => assertion.id,
    ),
    generated_at: NOW,
  }));
}

function scorecard(item: DemoEngagement): DeliveryScorecard {
  const candidate = item.claims.filter(
    (claim) => claim.status === "candidate",
  ).length;
  const accepted = item.claims.filter(
    (claim) => claim.status === "accepted",
  ).length;
  const rejected = item.claims.filter(
    (claim) => claim.status === "rejected",
  ).length;
  const deferred = item.claims.filter(
    (claim) => claim.status === "deferred",
  ).length;
  const resolved = item.contradictions.filter(
    (contradiction) => !contradiction.blocking,
  ).length;
  const packetComplete = item.artifacts.length === 7;
  return {
    engagement: {
      id: item.engagement.id,
      name: item.engagement.name,
      slug: item.engagement.slug,
      workflow_name: item.engagement.workflow_name,
    },
    milestones: {
      engagement_created: true,
      evidence_ready: item.evidence.length > 0,
      review_completed: candidate === 0 && item.claims.length > 0,
      workflows_approved:
        item.workflows.current?.status === "approved" &&
        item.workflows.target?.status === "approved",
      economics_approved: item.economics?.status === "approved",
      implementation_packet_completed: packetComplete,
    },
    claims: {
      total: item.claims.length,
      candidate,
      accepted,
      rejected,
      deferred,
      material_accepted: acceptedMaterialClaims(item).length,
    },
    contradictions: {
      total: item.contradictions.length,
      resolved,
      blocking_open: item.contradictions.filter(
        (contradiction) =>
          contradiction.blocking && contradiction.status !== "resolved",
      ).length,
    },
    packet: {
      complete: packetComplete,
      artifact_count: item.artifacts.length,
      expected_artifact_count: 7,
      packet_version: packetComplete ? 1 : null,
      completed_at: packetComplete ? NOW : null,
    },
    provider: {
      run_count: 1,
      providers: ["deterministic-hosted-demo"],
      model_ids: [],
      input_tokens: 0,
      output_tokens: 0,
      total_tokens: 0,
      latency_ms: 0,
      tokens_per_accepted_material_claim: 0,
    },
    assessments: item.assessments,
  };
}

function internalAlpha(state: DemoState): InternalAlphaScorecard {
  const cards = Object.values(state.engagements).map(scorecard);
  const assessments = Object.values(state.engagements).flatMap(
    (item) => item.assessments,
  );
  const method = (name: "ai_fde" | "conventional") => {
    const matching = assessments.filter(
      (assessment) =>
        assessment.delivery_method === name &&
        assessment.perspective === "operator" &&
        assessment.outcome === "completed",
    );
    const average = (field: keyof EngagementAssessment) =>
      matching.length
        ? matching.reduce((sum, item) => sum + Number(item[field]), 0) /
          matching.length
        : null;
    return {
      completed_operator_assessment_count: matching.length,
      distinct_workflow_count: matching.length,
      average_duration_minutes: average("duration_minutes"),
      average_usefulness_score: average("usefulness_score"),
      average_clarification_count: average("clarification_count"),
      average_rework_count: average("rework_count"),
      average_workaround_count: average("workaround_count"),
      average_trust_failure_count: average("trust_failure_count"),
    };
  };
  const aiFde = method("ai_fde");
  const conventional = method("conventional");
  const ready =
    aiFde.completed_operator_assessment_count >= 3 &&
    conventional.completed_operator_assessment_count >= 3;
  return {
    program: "internal-alpha",
    profile_count: cards.length,
    packet_complete_count: cards.filter((card) => card.packet.complete).length,
    accepted_material_claim_count: cards.reduce(
      (sum, card) => sum + card.claims.material_accepted,
      0,
    ),
    total_provider_tokens: 0,
    engagements: cards,
    comparison: {
      ready,
      minimum_completed_operator_assessments_per_method: 3,
      methods: { ai_fde: aiFde, conventional },
      absolute_difference: null,
      reason: ready
        ? null
        : "Collect at least three completed operator assessments per method before making comparative claims.",
    },
  };
}

export async function hostedDemoRequest<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  await Promise.resolve();
  const state = readState();
  const method = init?.method ?? "GET";

  if (path === "/auth/me") {
    return clone({
      id: OPERATOR_ID,
      display_name: "Hosted Demo FDE",
      auth_mode: "development",
      sanitized_data_allowed: false,
    }) as T;
  }
  if (path === "/auth/logout") return undefined as T;
  if (path === "/internal-alpha/scorecard")
    return clone(internalAlpha(state)) as T;
  if (path === "/engagements" && method === "GET") {
    return clone(
      Object.values(state.engagements).map((item) => item.engagement),
    ) as T;
  }
  if (path === "/engagements" && method === "POST") {
    const payload = requestBody<{
      name: string;
      workflow_name: string;
      primary_outcome: string;
    }>(init);
    const id = crypto.randomUUID();
    const profile: Profile = {
      id,
      slug: `${payload.name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}-${id.slice(0, 6)}`,
      company: payload.name,
      workflow: payload.workflow_name,
      outcome: payload.primary_outcome,
      accepted: [],
      rejected: [],
    };
    state.engagements[id] = seedEngagement(profile);
    state.engagements[id].evidence = [];
    writeState(state);
    return clone(state.engagements[id].engagement) as T;
  }

  const match = path.match(/^\/engagements\/([^/]+)(.*)$/);
  if (!match) throw new Error(`Unsupported hosted demo request: ${path}`);
  const engagementId = match[1];
  const suffix = match[2] || "";
  const item = requireEngagement(state, engagementId);

  if (!suffix && method === "GET") return clone(workspace(item)) as T;
  if (suffix === "/evidence" && method === "GET")
    return clone(item.evidence) as T;
  if (suffix === "/claims" && method === "GET") return clone(item.claims) as T;
  if (suffix === "/contradictions" && method === "GET")
    return clone(item.contradictions) as T;
  if (suffix === "/operating-model" && method === "GET")
    return clone(item.operatingModel) as T;
  if (suffix === "/workflows" && method === "GET")
    return clone(item.workflows) as T;
  if (suffix === "/economics" && method === "GET")
    return clone(item.economics) as T;
  if (suffix === "/implementation-packet" && method === "GET")
    return clone(item.artifacts) as T;
  if (suffix === "/implementation-specifications" && method === "GET")
    return clone(
      item.artifacts.find(
        (artifact) => artifact.artifact_type === "implementation_spec",
      ) ?? null,
    ) as T;
  if (suffix === "/delivery-scorecard" && method === "GET")
    return clone(scorecard(item)) as T;
  if (suffix === "/factory-handoff" && method === "GET") {
    return clone({
      customer_model: item.customerModel,
      opportunities: item.opportunities,
      readiness: item.readiness,
      packages: item.deploymentPackages,
      latest_retrieval: item.retrievalEvents.at(-1) ?? null,
    } satisfies FactoryHandoffWorkspace) as T;
  }
  if (suffix === "/data-lifecycle" && method === "GET") {
    return clone({
      status: item.engagement.data_lifecycle_status,
      retention_expires_at: item.engagement.retention_expires_at,
      membership_role: "owner",
      latest_export: item.latestExport,
      export_current: item.latestExport !== null,
      retention_blocked: false,
      can_delete: item.latestExport !== null,
    } satisfies EngagementDataLifecycle) as T;
  }

  const reviewMatch = suffix.match(/^\/claims\/([^/]+)\/review$/);
  if (reviewMatch && method === "POST") {
    const payload = requestBody<{
      decision: Claim["status"];
      reason: string | null;
    }>(init);
    const claim = item.claims.find(
      (candidate) => candidate.id === reviewMatch[1],
    );
    if (!claim) throw new Error("The candidate claim was not found.");
    claim.status = payload.decision;
    let assertionId: string | null = null;
    if (payload.decision === "accepted") {
      assertionId = `${claim.id.slice(0, 8)}-8000-4000-8000-${String(item.operatingModel.assertions.length + 1).padStart(12, "0")}`;
      item.operatingModel.assertions.push({
        id: assertionId,
        subject: claim.subject_text,
        subject_entity_id: assertionId,
        predicate: claim.predicate,
        object: claim.object_text,
        object_entity_id: null,
        value: claim.normalized_payload,
        status: "verified",
        confidence: claim.confidence,
        recorded_at: NOW,
        evidence: {
          file_name: claim.provenance[0].file_name,
          source_type: claim.provenance[0].source_type,
          source_timestamp: null,
          locator: claim.provenance[0].locator,
          quote: claim.provenance[0].quote,
          segment_id: claim.provenance[0].evidence_segment_id,
        },
      });
    }
    if (!item.claims.some((candidate) => candidate.status === "candidate")) {
      item.evidence.forEach((evidence) => {
        if (evidence.status === "needs_review") evidence.status = "complete";
      });
    }
    writeState(state);
    return clone({
      claim_id: claim.id,
      decision: payload.decision,
      assertion_id: assertionId,
    }) as T;
  }

  const contradictionMatch = suffix.match(
    /^\/contradictions\/([^/]+)\/resolve$/,
  );
  if (contradictionMatch && method === "POST") {
    const payload = requestBody<{
      resolution_type: NonNullable<Contradiction["resolution_type"]>;
      reason: string;
    }>(init);
    const contradiction = item.contradictions.find(
      (candidate) => candidate.id === contradictionMatch[1],
    );
    if (!contradiction) throw new Error("The contradiction was not found.");
    contradiction.status =
      payload.resolution_type === "accepted_exception" ||
      payload.resolution_type === "not_a_conflict"
        ? payload.resolution_type
        : "resolved";
    contradiction.blocking = false;
    contradiction.resolution_type = payload.resolution_type;
    contradiction.resolution_reason = payload.reason;
    contradiction.resolved_by_id = OPERATOR_ID;
    contradiction.resolved_at = NOW;
    writeState(state);
    return clone(contradiction) as T;
  }

  if (suffix === "/workflows/current/generate" && method === "POST") {
    item.workflows.current = createWorkflow(item, "current");
    writeState(state);
    return clone(item.workflows.current) as T;
  }
  if (suffix === "/workflows/target/generate" && method === "POST") {
    item.workflows.target = createWorkflow(item, "target");
    writeState(state);
    return clone(item.workflows.target) as T;
  }

  const stepMatch = suffix.match(/^\/workflows\/([^/]+)\/steps\/([^/]+)$/);
  if (stepMatch && method === "POST") {
    const workflow = [item.workflows.current, item.workflows.target].find(
      (candidate) => candidate?.id === stepMatch[1],
    );
    const workflowStep = workflow?.steps.find(
      (candidate) => candidate.id === stepMatch[2],
    );
    if (!workflowStep) throw new Error("The workflow step was not found.");
    Object.assign(workflowStep, requestBody<Partial<WorkflowStep>>(init));
    writeState(state);
    return clone(workflowStep) as T;
  }

  const approvalMatch = suffix.match(/^\/workflows\/([^/]+)\/approve$/);
  if (approvalMatch && method === "POST") {
    const workflow = [item.workflows.current, item.workflows.target].find(
      (candidate) => candidate?.id === approvalMatch[1],
    );
    if (!workflow) throw new Error("The workflow was not found.");
    workflow.status = "approved";
    workflow.approved_at = NOW;
    workflow.approval_reason =
      requestBody<{ reason?: string | null }>(init).reason ?? null;
    writeState(state);
    return clone(workflow) as T;
  }

  if (suffix === "/economics/calculate" && method === "POST") {
    item.economics = buildEconomics(
      item,
      requestBody<
        Record<
          string,
          { value: string; classification: EconomicValue["classification"] }
        >
      >(init),
    );
    writeState(state);
    return clone(item.economics) as T;
  }
  const economicsApproval = suffix.match(/^\/economics\/([^/]+)\/approve$/);
  if (economicsApproval && method === "POST") {
    if (!item.economics || item.economics.id !== economicsApproval[1])
      throw new Error("The economic case was not found.");
    item.economics.status = "approved";
    item.economics.approved_at = NOW;
    writeState(state);
    return clone(item.economics) as T;
  }
  if (suffix === "/implementation-packet/generate" && method === "POST") {
    item.artifacts = buildArtifacts(item);
    writeState(state);
    return clone(item.artifacts) as T;
  }
  if (
    suffix === "/implementation-specifications/generate" &&
    method === "POST"
  ) {
    item.artifacts = buildArtifacts(item);
    return clone(item.artifacts.at(-1)!) as T;
  }

  if (suffix === "/customer-factory-models/bootstrap" && method === "POST") {
    item.customerModel = await buildSyntheticCustomerModel(item);
    writeState(state);
    return clone(item.customerModel) as T;
  }

  if (suffix === "/factory-opportunities/bootstrap" && method === "POST") {
    const opportunity = await buildSyntheticOpportunity(item);
    item.opportunities = item.opportunities
      .map((current) =>
        current.opportunity_key === opportunity.opportunity_key &&
        current.status !== "STALE"
          ? { ...current, status: "STALE" as const }
          : current,
      )
      .concat(opportunity);
    writeState(state);
    return clone(opportunity) as T;
  }

  const opportunitySelection = suffix.match(
    /^\/factory-opportunities\/([^/]+)\/select$/,
  );
  if (opportunitySelection && method === "POST") {
    const opportunity = item.opportunities.find(
      (candidate) => candidate.id === opportunitySelection[1],
    );
    if (
      !opportunity ||
      !["ASSESSED", "RECOMMENDED"].includes(opportunity.status)
    ) {
      throw new Error("Only a current assessed opportunity can be selected.");
    }
    const reason = requestBody<{ reason: string }>(init).reason?.trim();
    if (!reason) throw new Error("Opportunity selection requires a rationale.");
    item.opportunities.forEach((current) => {
      if (current.status === "SELECTED") current.status = "STALE";
    });
    opportunity.status = "SELECTED";
    opportunity.selection_reason = reason;
    opportunity.selected_at = NOW;
    item.readiness = null;
    item.deploymentPackages.forEach((current) => {
      if (!["REVOKED", "SUPERSEDED"].includes(current.status)) {
        current.status = "STALE";
        current.state_reason =
          "A different synthetic opportunity was selected.";
      }
    });
    writeState(state);
    return clone(opportunity) as T;
  }

  if (suffix === "/fdlc-readiness/bootstrap" && method === "POST") {
    item.readiness = await buildSyntheticReadiness(item);
    writeState(state);
    return clone(item.readiness) as T;
  }

  const readinessApproval = suffix.match(
    /^\/fdlc-readiness\/([^/]+)\/approve$/,
  );
  if (readinessApproval && method === "POST") {
    if (
      !item.readiness ||
      item.readiness.id !== readinessApproval[1] ||
      item.readiness.status !== "DRAFT" ||
      item.readiness.overall_status !== "READY"
    ) {
      throw new Error(
        "Only a current all-stage READY assessment can be approved.",
      );
    }
    item.readiness.status = "APPROVED";
    item.readiness.approved_at = NOW;
    writeState(state);
    return clone(item.readiness) as T;
  }

  if (suffix === "/deployment-packages/bootstrap" && method === "POST") {
    const deploymentPackage = await buildSyntheticPackage(item);
    item.deploymentPackages.push(deploymentPackage);
    writeState(state);
    return clone(deploymentPackage) as T;
  }

  const packageTransition = suffix.match(
    /^\/deployment-packages\/([^/]+)\/(review|approve|publish|simulate-retrieval)$/,
  );
  if (packageTransition && method === "POST") {
    const deploymentPackage = item.deploymentPackages.find(
      (candidate) => candidate.id === packageTransition[1],
    );
    if (!deploymentPackage)
      throw new Error("The deployment package was not found.");
    const action = packageTransition[2];
    if (action === "review") {
      if (deploymentPackage.status !== "DRAFT")
        throw new Error("Only a draft package can enter review.");
      deploymentPackage.status = "READY_FOR_REVIEW";
    } else if (action === "approve") {
      if (deploymentPackage.status !== "READY_FOR_REVIEW")
        throw new Error("Only a review-ready package can be approved.");
      deploymentPackage.status = "APPROVED";
      deploymentPackage.approved_at = NOW;
      deploymentPackage.issued_at = NOW;
      const authorityBasis: FactorySourceReference = {
        kind: "APPROVED_INPUT",
        ref: `customer_factory_model:${item.customerModel!.id}`,
        version: item.customerModel!.version_number,
        sha256: item.customerModel!.content_digest,
      };
      deploymentPackage.approval = {
        decision_ref: {
          kind: "APPROVED_INPUT",
          ref: `factory_deployment_package_approval:${deploymentPackage.id}`,
          version: deploymentPackage.package_version,
          sha256: await syntheticSha256({
            package_id: deploymentPackage.package_id,
            package_version: deploymentPackage.package_version,
            approved_by: OPERATOR_ID,
            authority_basis_ref: authorityBasis,
            approved_at: NOW,
          }),
        },
        approved_by: OPERATOR_ID,
        authorized_by_ref: authorityBasis.ref,
        authority_basis_ref: authorityBasis,
        approved_at: NOW,
      };
      deploymentPackage.digest =
        await syntheticPackageDigest(deploymentPackage);
    } else if (action === "publish") {
      if (deploymentPackage.status !== "APPROVED" || !deploymentPackage.digest)
        throw new Error(
          "Only an approved digest-bound package can be published.",
        );
      item.deploymentPackages.forEach((current) => {
        if (
          current.id !== deploymentPackage.id &&
          current.status === "PUBLISHED"
        ) {
          current.status = "SUPERSEDED";
          current.state_reason = `Superseded by package ${deploymentPackage.package_id}.`;
        }
      });
      deploymentPackage.status = "PUBLISHED";
      deploymentPackage.published_at = NOW;
    } else {
      if (deploymentPackage.status !== "PUBLISHED" || !deploymentPackage.digest)
        throw new Error(
          "Mission Control can retrieve only a published package.",
        );
      if (
        deploymentPackage.digest !==
        (await syntheticPackageDigest(deploymentPackage))
      ) {
        throw new Error(
          "Mission Control rejected the simulated package because its canonical digest changed.",
        );
      }
      const event: PackageRetrievalEvent = {
        id: crypto.randomUUID(),
        engagement_id: item.engagement.id,
        package_id: deploymentPackage.package_id,
        package_version: deploymentPackage.package_version,
        requester_identity: "mission-control-hosted-demo",
        requester_system: "Mission Control · simulated",
        result: "RETRIEVED",
        digest: deploymentPackage.digest,
        correlation_id: crypto.randomUUID(),
        created_at: NOW,
      };
      item.retrievalEvents.push(event);
      writeState(state);
      return clone(event) as T;
    }
    writeState(state);
    return clone(deploymentPackage) as T;
  }

  if (suffix === "/assessments" && method === "POST") {
    const payload =
      requestBody<
        Omit<
          EngagementAssessment,
          "id" | "engagement_id" | "evaluator_id" | "created_at" | "updated_at"
        >
      >(init);
    const assessment: EngagementAssessment = {
      id: crypto.randomUUID(),
      engagement_id: engagementId,
      evaluator_id: OPERATOR_ID,
      ...payload,
      created_at: NOW,
      updated_at: NOW,
    };
    item.assessments = item.assessments.filter(
      (current) =>
        !(
          current.delivery_method === assessment.delivery_method &&
          current.perspective === assessment.perspective
        ),
    );
    item.assessments.push(assessment);
    writeState(state);
    return clone(assessment) as T;
  }
  if (suffix === "/data-lifecycle/retention" && method === "PUT") {
    item.engagement.retention_expires_at = requestBody<{
      retain_until: string;
    }>(init).retain_until;
    writeState(state);
    return clone(item.engagement) as T;
  }
  if (suffix === "/data-lifecycle/deletion" && method === "POST") {
    const receipt: EngagementDeletionReceipt = {
      id: crypto.randomUUID(),
      engagement_id: engagementId,
      status: "completed",
      data_classification: "synthetic",
      export_id: item.latestExport?.id ?? "",
      source_fingerprint: item.latestExport?.source_fingerprint ?? "",
      archive_hash: item.latestExport?.archive_hash ?? "",
      database_row_count: 0,
      evidence_object_count: item.evidence.length,
      failure_code: null,
      requested_at: NOW,
      completed_at: NOW,
    };
    delete state.engagements[engagementId];
    writeState(state);
    return clone(receipt) as T;
  }
  if ((suffix === "/evidence" || suffix === "/notes") && method === "POST") {
    const isNote = suffix === "/notes";
    const form = init?.body instanceof FormData ? init.body : null;
    const note = isNote
      ? requestBody<{ title: string; content: string }>(init)
      : null;
    const file = form?.get("file");
    const fileName =
      file instanceof File ? file.name : note?.title || "operator-note.md";
    const evidence: Evidence = {
      id: crypto.randomUUID(),
      engagement_id: engagementId,
      file_name: fileName,
      content_type: file instanceof File ? file.type : "text/markdown",
      content_hash: "d".repeat(64),
      byte_count:
        file instanceof File ? file.size : (note?.content.length ?? 0),
      source_type: isNote ? "operator_note" : "upload",
      source_timestamp: null,
      status: "complete",
      error_message: null,
      created_at: NOW,
    };
    item.evidence.push(evidence);
    writeState(state);
    return clone(evidence) as T;
  }

  throw new Error(`Unsupported hosted demo request: ${method} ${path}`);
}

export async function hostedDemoExport(
  engagementId: string,
): Promise<{ blob: Blob; exportId: string; filename: string }> {
  const state = readState();
  const item = requireEngagement(state, engagementId);
  const exportId = crypto.randomUUID();
  const content = JSON.stringify(
    {
      notice: "Synthetic browser-local hosted demo export",
      engagement: item.engagement,
      claims: item.claims,
      workflows: item.workflows,
      economics: item.economics,
      artifacts: item.artifacts,
    },
    null,
    2,
  );
  item.latestExport = {
    id: exportId,
    schema_version: "hosted-demo-v1",
    source_fingerprint: "a".repeat(64),
    archive_hash: "b".repeat(64),
    byte_count: content.length,
    record_count:
      item.claims.length + item.artifacts.length + item.assessments.length,
    evidence_object_count: item.evidence.length,
    exported_at: new Date().toISOString(),
  };
  writeState(state);
  return {
    blob: new Blob([content], { type: "application/json" }),
    exportId,
    filename: `ai-fde-${item.engagement.slug}-hosted-demo.json`,
  };
}
