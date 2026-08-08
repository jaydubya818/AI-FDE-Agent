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
