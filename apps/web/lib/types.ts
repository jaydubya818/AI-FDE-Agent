import type {
  BackendEnum,
  MissingBackendFields,
} from "./backend-contract.generated";

export type Engagement = {
  id: string;
  name: string;
  slug: string;
  workflow_name: string;
  primary_outcome: string;
  lifecycle_stage: BackendEnum<"engagementLifecycleStage">;
  data_classification: BackendEnum<"engagementDataClassification">;
  data_lifecycle_status: BackendEnum<"engagementDataLifecycleStatus">;
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

export type DesignPartnerAuthorizedUser = {
  operator_id: string;
  display_name: string;
  role: "owner" | "operator" | "viewer";
};

export type DesignPartnerQualification = {
  id: string;
  engagement_id: string;
  partner_key: string;
  organization: string;
  status: "ACTIVE" | "SUSPENDED" | "REVOKED";
  qualification_state: "CONFIGURED" | "IN_PROGRESS" | "BLOCKED" | "QUALIFIED";
  authorized_users: DesignPartnerAuthorizedUser[];
  authorized_data_source_keys: string[];
  authorized_repository_refs: string[];
  allowed_workflow_classes: string[];
  data_classification: "PUBLIC" | "INTERNAL" | "CONFIDENTIAL" | "RESTRICTED";
  retention_days: number;
  authorization_basis_ref: string;
  created_at: string;
  updated_at: string;
};

export type Evidence = {
  id: string;
  engagement_id: string;
  file_name: string;
  content_type: string;
  content_hash: string;
  byte_count: number;
  source_type: BackendEnum<"evidenceSourceType">;
  source_timestamp: string | null;
  design_partner_qualification_id: string | null;
  authorized_source_key: string | null;
  authorized_workflow_class: string | null;
  data_classification: string | null;
  status: BackendEnum<"evidenceStatus">;
  error_message: string | null;
  created_at: string;
};

export type Provenance = {
  claim_evidence_id: string;
  evidence_segment_id: string;
  evidence_asset_id: string;
  file_name: string;
  source_type: BackendEnum<"evidenceSourceType">;
  source_timestamp: string | null;
  locator: Record<string, unknown>;
  quote: string;
  start_offset: number;
  end_offset: number;
};

export type Claim = {
  id: string;
  claim_kind: BackendEnum<"claimKind">;
  subject_text: string;
  predicate: BackendEnum<"claimPredicate">;
  object_text: string | null;
  summary: string;
  normalized_payload: Record<string, unknown>;
  confidence: string;
  materiality: BackendEnum<"claimMateriality">;
  status: BackendEnum<"claimStatus">;
  created_at: string;
  provenance: Provenance[];
};

export type Contradiction = {
  id: string;
  summary: string;
  status: BackendEnum<"contradictionStatus">;
  blocking: boolean;
  left_claim_id: string;
  right_claim_id: string;
  resolution_type: BackendEnum<"contradictionResolutionType"> | null;
  resolution_reason: string | null;
  resolved_by_id: string | null;
  resolved_at: string | null;
  created_at: string;
};

export type Entity = {
  id: string;
  entity_type: BackendEnum<"entityType">;
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
    source_type: BackendEnum<"evidenceSourceType">;
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
  step_type: BackendEnum<"workflowStepType">;
  actor_label: string | null;
  system_label: string | null;
  allocation: BackendEnum<"workflowAllocation">;
  rationale: string;
  controls: string[];
  source_assertion_id: string | null;
};

export type Workflow = {
  id: string;
  workflow_kind: BackendEnum<"workflowKind">;
  version_number: number;
  name: string;
  objective: string;
  status: BackendEnum<"workflowStatus">;
  source_workflow_id: string | null;
  source_assertion_ids: string[];
  generated_by: BackendEnum<"workflowGeneratedBy">;
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
  status: BackendEnum<"economicCaseStatus">;
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
  artifact_type: BackendEnum<"artifactType">;
  packet_version: number;
  version_number: number;
  status: BackendEnum<"artifactStatus">;
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
  status: BackendEnum<"engagementDataLifecycleStatus">;
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
  status: BackendEnum<"deletionReceiptStatus">;
  data_classification: BackendEnum<"deletionReceiptDataClassification">;
  export_id: string;
  source_fingerprint: string;
  archive_hash: string;
  database_row_count: number;
  evidence_object_count: number;
  failure_code: string | null;
  requested_at: string;
  completed_at: string | null;
};

export type DeliveryMethod = BackendEnum<"assessmentDeliveryMethod">;
export type AssessmentPerspective = BackendEnum<"assessmentPerspective">;
export type AssessmentOutcome = BackendEnum<"assessmentOutcome">;

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

export type FactorySourceReference = {
  kind: "EVIDENCE" | "VERIFIED_CLAIM" | "APPROVED_INPUT" | "ASSUMPTION";
  ref: string;
  version: number | null;
  sha256: string;
};

export type FactoryImmutableVersionReference = {
  id: string;
  version: number;
  digest: string;
};

export type TraceableFactoryFact = {
  key: string;
  label: string;
  description: string;
  provenance_refs: FactorySourceReference[];
  attributes: Record<string, unknown>;
};

export type CustomerFactoryModel = {
  id: string;
  engagement_id: string;
  version_number: number;
  status: BackendEnum<"customerFactoryModelStatus">;
  organization: TraceableFactoryFact;
  systems: TraceableFactoryFact[];
  repositories: TraceableFactoryFact[];
  environments: TraceableFactoryFact[];
  workflows: TraceableFactoryFact[];
  policies: TraceableFactoryFact[];
  authority_boundaries: TraceableFactoryFact[];
  constraints: TraceableFactoryFact[];
  risks: TraceableFactoryFact[];
  baselines: TraceableFactoryFact[];
  evidence_refs: FactorySourceReference[];
  verified_claim_refs: FactorySourceReference[];
  assumption_refs: FactorySourceReference[];
  factory_opportunity_refs: FactorySourceReference[];
  content_digest: string;
  approved_at: string | null;
  stale_reason: string | null;
  created_at: string;
};

export type FactoryOpportunity = {
  id: string;
  engagement_id: string;
  opportunity_key: string;
  version_number: number;
  status: BackendEnum<"factoryOpportunityStatus">;
  name: string;
  description: string;
  source_workflow_ref: FactoryImmutableVersionReference;
  customer_factory_model_id: string;
  customer_factory_model_version: number;
  value_score: number;
  verifiability_score: number;
  readiness_score: number;
  risk_score: number;
  autonomy_potential: number;
  priority_score: number;
  factors: Record<string, number>;
  rubric: Record<string, Record<string, number>>;
  rubric_version: string;
  economics_ref: FactorySourceReference;
  evidence_refs: FactorySourceReference[];
  rationale: string[];
  blockers: string[];
  recommendation: string;
  content_digest: string;
  selection_reason: string | null;
  selected_at: string | null;
  rejection_reason: string | null;
  rejected_at: string | null;
  stale_reason: string | null;
  created_at: string;
};

export type FDLCReadinessStage = {
  stage: BackendEnum<"fdlcReadinessStage">;
  status: BackendEnum<"fdlcReadinessStatus">;
  score: number;
  evidence_refs: FactorySourceReference[];
  blockers: string[];
  risks: string[];
  decisions: FactorySourceReference[];
  required_artifacts: string[];
  owner: string | null;
  next_actions: string[];
  criteria: Array<{
    key: string;
    label: string;
    satisfied: boolean;
    blocking: boolean;
    explanation: string;
    basis_refs: FactorySourceReference[];
    next_action: string | null;
  }>;
  explanation: string;
  updated_at: string;
};

export type FDLCReadinessAssessment = {
  id: string;
  engagement_id: string;
  version_number: number;
  status: BackendEnum<"fdlcReadinessAssessmentStatus">;
  overall_status: FDLCReadinessStage["status"];
  customer_factory_model_id: string;
  customer_factory_model_version: number;
  selected_opportunity_id: string;
  selected_opportunity_version: number;
  current_workflow_ref: { id: string; version: number; digest: string };
  target_workflow_ref: { id: string; version: number; digest: string };
  stages: FDLCReadinessStage[];
  content_digest: string;
  approved_at: string | null;
  stale_reason: string | null;
  created_at: string;
};

export type FactoryContractRequirement = {
  key: string;
  statement: string;
};

export type FactoryPlanAssertion = {
  assertion_id: string;
  title: string;
  outcome: string;
  verification_method: "COMMAND" | "TEST" | "BROWSER" | "MANUAL" | "CHECKLIST";
  pass_condition: string;
  required_evidence: string;
  requires_independent_validation: boolean;
  waiver_allowed: boolean;
};

export type FactoryWorkOrderBlueprint = {
  key: string;
  title: string;
  outcome: string;
  requirements: string[];
  acceptance_criterion_refs: string[];
  constraints: string[];
  requested_code_scopes: string[];
  capability_requirement_refs: string[];
  verification_requirement_refs: string[];
  authority_boundary_refs: string[];
  sequence: number;
  execution_role: "WORKER" | "VALIDATOR";
  is_mutating: boolean;
  priority: 1 | 2 | 3 | 4;
  risk_level: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  required_approvals: string[];
  dependencies: string[];
  assertion_ids: string[];
};

export type DeploymentPackage = {
  id: string;
  engagement_id: string;
  package_id: string;
  package_version: number;
  schema_version: "fdlc.factory-deployment-package/v1";
  status: BackendEnum<"deploymentPackageStatus">;
  issuer: {
    issuer_id: string;
    issuer_type: "FDLC_FACTORY_ENGINEER";
    environment: string;
    authority_scope: "DEPLOYMENT_PACKAGE_PUBLISH";
  };
  source: {
    customer_factory_model: { id: string; version: number; digest: string };
    current_workflow: { id: string; version: number; digest: string };
    target_workflow: { id: string; version: number; digest: string };
    readiness_assessment: { id: string; version: number; digest: string };
    factory_opportunity: { id: string; version: number; digest: string };
  };
  target: {
    workspace_ref: string;
    repository_ref: string;
    requested_code_scopes: string[];
    semantic_execution_workflow_ref: string;
    environment_class: string;
  };
  deployment_intent: {
    mission_title: string;
    mission_context: string;
    stop_condition: string;
    plan_summary: string;
    rollback_approach: string;
    objective: string;
    intent: string;
    specification: string;
    acceptance_criteria: Array<{
      key: string;
      statement: string;
      verification_method: string;
    }>;
    constraints: FactoryContractRequirement[];
    required_capabilities: FactoryContractRequirement[];
    required_agents: FactoryContractRequirement[];
    required_skills: FactoryContractRequirement[];
    required_tools: FactoryContractRequirement[];
    model_requirements: FactoryContractRequirement[];
    context_requirements: FactoryContractRequirement[];
    environment_requirements: FactoryContractRequirement[];
    authority_boundaries: Array<{
      key: string;
      subject: string;
      maximum_authority: string;
      prohibited_actions: string[];
    }>;
    policy_requirements: FactoryContractRequirement[];
    approval_requirements: FactoryContractRequirement[];
    verification_contract: Array<{
      key: string;
      statement: string;
      evidence_required: string[];
      independent: boolean;
    }>;
    evaluation_requirements: FactoryContractRequirement[];
    rollback_requirements: FactoryContractRequirement[];
    observability_requirements: FactoryContractRequirement[];
    risk_summary: Array<{ key: string; statement: string }>;
    economics_baseline: Record<string, unknown>;
    evidence_refs: FactorySourceReference[];
    decision_refs: FactorySourceReference[];
    provenance: FactorySourceReference[];
    plan_assertions: FactoryPlanAssertion[];
    work_order_blueprints: FactoryWorkOrderBlueprint[];
  };
  digest: string | null;
  approval: {
    decision_ref: FactorySourceReference;
    approved_by: string;
    authorized_by_ref: string;
    authority_basis_ref: FactorySourceReference;
    approved_at: string;
  } | null;
  issued_at: string | null;
  approved_at: string | null;
  published_at: string | null;
  state_reason: string | null;
  created_at: string;
};

export type PackageRetrievalEvent = {
  id: string;
  engagement_id: string;
  package_id: string;
  package_version: number;
  requester_identity: string;
  requester_system: string;
  result: string;
  digest: string | null;
  correlation_id: string;
  created_at: string;
};

export type FactoryHandoffWorkspace = {
  customer_model: CustomerFactoryModel | null;
  opportunities: FactoryOpportunity[];
  readiness: FDLCReadinessAssessment | null;
  packages: DeploymentPackage[];
  latest_retrieval: PackageRetrievalEvent | null;
};

export type FactoryHandoffPrerequisites = {
  engagement_id: string;
  organization_key: string;
  organization_label: string;
  workflow_name: string;
  primary_outcome: string;
  evidence_refs: FactorySourceReference[];
  verified_claim_refs: FactorySourceReference[];
  current_workflow_ref: FactoryImmutableVersionReference | null;
  target_workflow_ref: FactoryImmutableVersionReference | null;
  economic_case_ref: FactorySourceReference | null;
  implementation_artifact_refs: FactorySourceReference[];
};

export type CustomerFactoryModelInput = Pick<
  CustomerFactoryModel,
  | "organization"
  | "systems"
  | "repositories"
  | "environments"
  | "workflows"
  | "policies"
  | "authority_boundaries"
  | "constraints"
  | "risks"
  | "baselines"
  | "evidence_refs"
  | "verified_claim_refs"
  | "assumption_refs"
  | "factory_opportunity_refs"
>;

export type FactoryOpportunityFactors = {
  workflow_frequency: number;
  human_effort: number;
  cycle_time: number;
  repeatability: number;
  standardization: number;
  evidence_quality: number;
  deterministic_verifiability: number;
  blast_radius: number;
  system_accessibility: number;
  data_sensitivity: number;
  implementation_complexity: number;
  expected_economic_value: number;
  autonomy_potential: number;
};

export type FactoryOpportunityInput = {
  customer_factory_model_id: string;
  opportunity: {
    opportunity_key: string;
    name: string;
    description: string;
    source_workflow_ref: FactoryImmutableVersionReference;
    factors: FactoryOpportunityFactors;
    economics_ref: FactorySourceReference;
    evidence_refs: FactorySourceReference[];
    blockers: string[];
  };
};

export type ReadinessCriterionInput = {
  key: string;
  label: string;
  satisfied: boolean;
  blocking: boolean;
  explanation: string;
  basis_refs: FactorySourceReference[];
  next_action: string | null;
};

export type ReadinessStageInput = {
  stage: FDLCReadinessStage["stage"];
  criteria: ReadinessCriterionInput[];
  risks: string[];
  decisions: FactorySourceReference[];
  required_artifacts: string[];
  owner: string | null;
};

export type ReadinessAssessmentInput = {
  customer_factory_model_id: string;
  selected_opportunity_id: string;
  current_workflow_id: string;
  target_workflow_id: string;
  assessment: { stages: ReadinessStageInput[] };
};

export type DeploymentPackageInput = {
  customer_factory_model_id: string;
  readiness_assessment_id: string;
  factory_opportunity_id: string;
  target: DeploymentPackage["target"];
  deployment_intent: DeploymentPackage["deployment_intent"];
};

type AssertNoMissingBackendFields<Value extends Record<string, never>> = Value;

export type BackendResponseContractParity = AssertNoMissingBackendFields<{
  assertion: MissingBackendFields<"assertion", Assertion>;
  claim: MissingBackendFields<"claim", Claim>;
  contradiction: MissingBackendFields<"contradiction", Contradiction>;
  customerFactoryModel: MissingBackendFields<
    "customerFactoryModel",
    CustomerFactoryModel
  >;
  deploymentPackage: MissingBackendFields<
    "deploymentPackage",
    DeploymentPackage
  >;
  designPartnerQualification: MissingBackendFields<
    "designPartnerQualification",
    DesignPartnerQualification
  >;
  deliveryScorecard: MissingBackendFields<
    "deliveryScorecard",
    DeliveryScorecard
  >;
  economicCase: MissingBackendFields<"economicCase", EconomicCase>;
  engagement: MissingBackendFields<"engagement", Engagement>;
  engagementAssessment: MissingBackendFields<
    "engagementAssessment",
    EngagementAssessment
  >;
  engagementDataLifecycle: MissingBackendFields<
    "engagementDataLifecycle",
    EngagementDataLifecycle
  >;
  engagementDeletionReceipt: MissingBackendFields<
    "engagementDeletionReceipt",
    EngagementDeletionReceipt
  >;
  engagementWorkspace: MissingBackendFields<
    "engagementWorkspace",
    EngagementWorkspace
  >;
  entity: MissingBackendFields<"entity", Entity>;
  evidence: MissingBackendFields<"evidence", Evidence>;
  factoryHandoffPrerequisites: MissingBackendFields<
    "factoryHandoffPrerequisites",
    FactoryHandoffPrerequisites
  >;
  factoryHandoffWorkspace: MissingBackendFields<
    "factoryHandoffWorkspace",
    FactoryHandoffWorkspace
  >;
  factoryOpportunity: MissingBackendFields<
    "factoryOpportunity",
    FactoryOpportunity
  >;
  fdlcReadinessAssessment: MissingBackendFields<
    "fdlcReadinessAssessment",
    FDLCReadinessAssessment
  >;
  implementationArtifact: MissingBackendFields<
    "implementationArtifact",
    ImplementationArtifact
  >;
  internalAlphaScorecard: MissingBackendFields<
    "internalAlphaScorecard",
    InternalAlphaScorecard
  >;
  operatingModel: MissingBackendFields<"operatingModel", OperatingModel>;
  packageRetrievalEvent: MissingBackendFields<
    "packageRetrievalEvent",
    PackageRetrievalEvent
  >;
  provenance: MissingBackendFields<"provenance", Provenance>;
  workflow: MissingBackendFields<"workflow", Workflow>;
  workflowStep: MissingBackendFields<"workflowStep", WorkflowStep>;
  workflowWorkspace: MissingBackendFields<
    "workflowWorkspace",
    WorkflowWorkspace
  >;
}>;
