export type Engagement = {
  id: string;
  name: string;
  slug: string;
  primary_outcome: string;
  lifecycle_stage: string;
  data_classification: "synthetic" | "sanitized";
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
};

export type EconomicCase = {
  id: string;
  version_number: number;
  status: "draft" | "approved" | "stale";
  source_target_workflow_id: string;
  formula_version: string;
  inputs: Record<string, EconomicValue>;
  outputs: Record<string, EconomicValue>;
  assumptions: string[];
  approved_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ImplementationArtifact = {
  id: string;
  artifact_type: "implementation_spec";
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
