export type Engagement = {
  id: string;
  name: string;
  slug: string;
  workflow_name: string;
  primary_outcome: string;
  lifecycle_stage: string;
  data_classification: "synthetic" | "sanitized";
  data_lifecycle_status: "active" | "deletion_processing" | "deletion_failed";
  retention_expires_at: string | null;
  created_at: string;
  updated_at: string;
};

export type EngagementWorkspace = {
  engagement: Engagement;
  counts: {
    evidence: number;
    candidate_claims: number;
    verified_assertions: number;
  };
};

export type Evidence = {
  id: string;
  file_name: string;
  content_type: string;
  content_hash: string;
  byte_count: number;
  source_type: string;
  source_timestamp: string | null;
  status: "queued" | "processing" | "needs_review" | "failed" | "complete";
  error_message: string | null;
  created_at: string;
};

export type Provenance = {
  claim_evidence_id: string;
  evidence_segment_id: string;
  evidence_asset_id: string;
  file_name: string;
  source_type: string;
  source_timestamp: string | null;
  locator: Record<string, unknown>;
  quote: string;
  start_offset: number;
  end_offset: number;
};

export type Claim = {
  id: string;
  claim_kind: "entity" | "relationship" | "rule" | "exception";
  subject_text: string;
  predicate: string;
  object_text: string | null;
  summary: string;
  normalized_payload: Record<string, unknown>;
  confidence: string;
  materiality: string;
  status: "candidate" | "accepted" | "rejected" | "deferred";
  created_at: string;
  provenance: Provenance[];
};

export type Contradiction = {
  id: string;
  summary: string;
  status: string;
  blocking: boolean;
  left_claim_id: string;
  right_claim_id: string;
  resolution_type: string | null;
  resolution_reason: string | null;
  resolved_by_id: string | null;
  resolved_at: string | null;
  created_at: string;
};

export type Entity = {
  id: string;
  entity_type: string;
  canonical_key: string;
  display_name: string;
  status: string;
  created_at: string;
};

export type Assertion = {
  id: string;
  subject: string;
  subject_entity_id: string;
  predicate: string;
  object: string | null;
  object_entity_id: string | null;
  value: Record<string, unknown>;
  status: string;
  confidence: string;
  recorded_at: string;
  evidence: {
    file_name: string;
    source_type: string;
    source_timestamp: string | null;
    locator: Record<string, unknown>;
    quote: string;
    segment_id: string;
  };
};

export type OperatingModel = {
  entities: Entity[];
  assertions: Assertion[];
};

export type WorkflowStep = {
  id: string;
  step_key: string;
  position: number;
  name: string;
  description: string;
  step_type: string;
  actor_label: string | null;
  system_label: string | null;
  allocation: "human" | "software" | "ai" | "ai_human";
  rationale: string;
  controls: string[];
  source_assertion_id: string | null;
};

export type Workflow = {
  id: string;
  workflow_kind: "current" | "target";
  version_number: number;
  name: string;
  objective: string;
  status: "draft" | "approved" | "stale";
  source_workflow_id: string | null;
  source_assertion_ids: string[];
  generated_by: string;
  approved_at: string | null;
  approval_reason: string | null;
  created_at: string;
  updated_at: string;
  steps: WorkflowStep[];
};

export type WorkflowWorkspace = {
  current: Workflow | null;
  target: Workflow | null;
};

export type EvidenceClassification =
  "measured" | "calculated" | "estimated" | "synthetic" | "simulated";

export type EconomicValue = {
  value: string | null;
  unit: string;
  classification: EvidenceClassification;
  formula?: string;
  provenance?: {
    source: string;
    source_classification: EvidenceClassification;
    transform: string;
  };
};

export type EconomicScenario = {
  label: string;
  description: string;
  inputs: Record<string, EconomicValue>;
  outputs: Record<string, EconomicValue>;
};

export type EconomicCase = {
  id: string;
  version_number: number;
  status: "draft" | "approved" | "stale";
  source_target_workflow_id: string;
  formula_version: string;
  inputs: Record<string, EconomicValue>;
  outputs: Record<string, EconomicValue>;
  scenarios: Record<"low" | "base" | "high", EconomicScenario>;
  assumptions: string[];
  approved_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ImplementationArtifact = {
  id: string;
  artifact_type:
    | "prd"
    | "architecture"
    | "business_rules"
    | "integration_requirements"
    | "approval_controls"
    | "evaluation_plan"
    | "implementation_spec";
  packet_version: number;
  version_number: number;
  status: "current" | "stale";
  title: string;
  content: string;
  content_hash: string;
  source_current_workflow_id: string;
  source_target_workflow_id: string;
  economic_case_id: string;
  source_assertion_ids: string[];
  generated_at: string;
};

export type EngagementExport = {
  id: string;
  schema_version: string;
  source_fingerprint: string;
  archive_hash: string;
  byte_count: number;
  record_count: number;
  evidence_object_count: number;
  exported_at: string;
};

export type EngagementDataLifecycle = {
  status: "active" | "deletion_processing" | "deletion_failed";
  retention_expires_at: string | null;
  membership_role: "owner" | "operator" | "viewer";
  latest_export: EngagementExport | null;
  export_current: boolean;
  retention_blocked: boolean;
  can_delete: boolean;
};

export type EngagementDeletionReceipt = {
  id: string;
  engagement_id: string;
  status: "processing" | "completed" | "failed";
  data_classification: "synthetic" | "sanitized";
  export_id: string;
  source_fingerprint: string;
  archive_hash: string;
  database_row_count: number;
  evidence_object_count: number;
  failure_code: string | null;
  requested_at: string;
  completed_at: string | null;
};

export type DeliveryMethod = "ai_fde" | "conventional";
export type AssessmentPerspective = "operator" | "engineering";
export type AssessmentOutcome = "completed" | "blocked" | "abandoned";

export type EngagementAssessment = {
  id: string;
  engagement_id: string;
  evaluator_id: string;
  delivery_method: DeliveryMethod;
  perspective: AssessmentPerspective;
  outcome: AssessmentOutcome;
  duration_minutes: number;
  usefulness_score: number;
  clarification_count: number;
  rework_count: number;
  workaround_count: number;
  trust_failure_count: number;
  notes: string | null;
  created_at: string;
  updated_at: string;
};

export type DeliveryScorecard = {
  engagement: {
    id: string;
    name: string;
    slug: string;
    workflow_name: string;
  };
  milestones: {
    engagement_created: boolean;
    evidence_ready: boolean;
    review_completed: boolean;
    workflows_approved: boolean;
    economics_approved: boolean;
    implementation_packet_completed: boolean;
  };
  claims: {
    total: number;
    candidate: number;
    accepted: number;
    rejected: number;
    deferred: number;
    material_accepted: number;
  };
  contradictions: {
    total: number;
    resolved: number;
    blocking_open: number;
  };
  packet: {
    complete: boolean;
    artifact_count: number;
    expected_artifact_count: number;
    packet_version: number | null;
    completed_at: string | null;
  };
  provider: {
    run_count: number;
    providers: string[];
    model_ids: string[];
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    latency_ms: number;
    tokens_per_accepted_material_claim: number | null;
  };
  assessments: EngagementAssessment[];
};

export type MethodComparison = {
  completed_operator_assessment_count: number;
  distinct_workflow_count: number;
  average_duration_minutes: number | null;
  average_usefulness_score: number | null;
  average_clarification_count: number | null;
  average_rework_count: number | null;
  average_workaround_count: number | null;
  average_trust_failure_count: number | null;
};

export type InternalAlphaScorecard = {
  program: "internal-alpha";
  profile_count: number;
  packet_complete_count: number;
  accepted_material_claim_count: number;
  total_provider_tokens: number;
  engagements: DeliveryScorecard[];
  comparison: {
    ready: boolean;
    minimum_completed_operator_assessments_per_method: number;
    methods: Record<DeliveryMethod, MethodComparison>;
    absolute_difference: {
      duration_minutes: number;
      rework_count: number;
      trust_failure_count: number;
      usefulness_score: number;
    } | null;
    reason: string | null;
  };
};
