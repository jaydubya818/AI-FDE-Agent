import type {
  Claim,
  Contradiction,
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
  ImplementationArtifact,
  InternalAlphaScorecard,
  OperatingModel,
  Workflow,
  WorkflowStep,
  WorkflowWorkspace,
} from "./types";

const STORAGE_KEY = "ai-fde-hosted-demo-v2";
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
};

type DemoState = {
  version: 2;
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
  };
}

function initialState(): DemoState {
  return {
    version: 2,
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
    if (state.version === 2) return state;
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
