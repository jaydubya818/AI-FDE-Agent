"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import { CheckIcon, ShieldIcon } from "@/components/icons";
import {
  approveEconomics,
  approveWorkflow,
  calculateEconomics,
  generateCurrentWorkflow,
  generateImplementationPacket,
  generateTargetWorkflow,
  getEconomics,
  getImplementationPacket,
  getWorkflows,
  updateWorkflowStep,
} from "@/lib/api";
import type {
  EconomicCase,
  EvidenceClassification,
  ImplementationArtifact,
  Workflow,
  WorkflowStep,
  WorkflowWorkspace,
} from "@/lib/types";

type LifecycleData = {
  workflows: WorkflowWorkspace;
  economics: EconomicCase | null;
  artifacts: ImplementationArtifact[];
};

type EconomicKey =
  | "annual_volume"
  | "current_minutes_per_item"
  | "target_minutes_per_item"
  | "loaded_hourly_cost"
  | "implementation_cost"
  | "annual_operating_cost";

type EconomicDraft = Record<
  EconomicKey,
  { value: string; classification: EvidenceClassification }
>;

const economicFields: Array<{ key: EconomicKey; label: string; unit: string }> =
  [
    {
      key: "annual_volume",
      label: "Annual item volume",
      unit: "items / year",
    },
    {
      key: "current_minutes_per_item",
      label: "Current effort",
      unit: "minutes / item",
    },
    {
      key: "target_minutes_per_item",
      label: "Target effort",
      unit: "minutes / item",
    },
    {
      key: "loaded_hourly_cost",
      label: "Loaded labor cost",
      unit: "USD / hour",
    },
    { key: "implementation_cost", label: "Implementation cost", unit: "USD" },
    {
      key: "annual_operating_cost",
      label: "Annual operating cost",
      unit: "USD / year",
    },
  ];

const defaultEconomics: EconomicDraft = {
  annual_volume: { value: "24000", classification: "synthetic" },
  current_minutes_per_item: { value: "18", classification: "synthetic" },
  target_minutes_per_item: { value: "8", classification: "synthetic" },
  loaded_hourly_cost: { value: "42", classification: "synthetic" },
  implementation_cost: { value: "85000", classification: "synthetic" },
  annual_operating_cost: { value: "18000", classification: "synthetic" },
};

const classifications: EvidenceClassification[] = [
  "measured",
  "estimated",
  "synthetic",
  "simulated",
];

export function LifecycleWorkspace({
  engagementId,
  modelVersion,
  blockingContradictions,
  onProgress,
}: {
  engagementId: string;
  modelVersion: string;
  blockingContradictions: number;
  onProgress: (progress: {
    current: boolean;
    target: boolean;
    economics: boolean;
    specification: boolean;
  }) => void;
}) {
  const [data, setData] = useState<LifecycleData | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<{
    tone: "success" | "error";
    text: string;
  } | null>(null);
  const [overrideReason, setOverrideReason] = useState("");
  const [economicDraft, setEconomicDraft] =
    useState<EconomicDraft>(defaultEconomics);
  const [selectedArtifactType, setSelectedArtifactType] = useState<
    ImplementationArtifact["artifact_type"]
  >("implementation_spec");

  const load = useCallback(async () => {
    const [workflows, economics, artifacts] = await Promise.all([
      getWorkflows(engagementId),
      getEconomics(engagementId),
      getImplementationPacket(engagementId),
    ]);
    setData({ workflows, economics, artifacts });
    onProgress({
      current: workflows.current?.status === "approved",
      target: workflows.target?.status === "approved",
      economics: economics?.status === "approved",
      specification:
        artifacts.length === 7 &&
        artifacts.every((artifact) => artifact.status === "current"),
    });
  }, [engagementId, onProgress]);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      load()
        .catch((reason: unknown) =>
          setNotice({
            tone: "error",
            text:
              reason instanceof Error
                ? reason.message
                : "The lifecycle state could not be loaded.",
          }),
        )
        .finally(() => setLoading(false));
    }, 0);
    return () => window.clearTimeout(timeout);
  }, [load, modelVersion]);

  async function runAction(
    key: string,
    action: () => Promise<unknown>,
    success: string,
  ) {
    setBusy(key);
    setNotice(null);
    try {
      await action();
      await load();
      setNotice({ tone: "success", text: success });
    } catch (reason) {
      setNotice({
        tone: "error",
        text:
          reason instanceof Error
            ? reason.message
            : "The lifecycle action could not be completed.",
      });
    } finally {
      setBusy(null);
    }
  }

  async function handleEconomics(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runAction(
      "economics-calculate",
      () =>
        calculateEconomics(engagementId, {
          ...economicDraft,
          assumptions: [
            "Synthetic Acme values for architecture validation; replace before customer use.",
          ],
        }),
      "The deterministic economic case was recalculated from the labeled inputs.",
    );
  }

  async function handleCopyArtifact(content: string) {
    try {
      await navigator.clipboard.writeText(content);
      setNotice({
        tone: "success",
        text: "The selected artifact was copied to the clipboard.",
      });
    } catch {
      setNotice({
        tone: "error",
        text: "The browser could not copy the selected artifact.",
      });
    }
  }

  if (loading) {
    return (
      <div
        aria-live="polite"
        className="surface mt-8 rounded-2xl p-8 text-sm font-bold text-[var(--ink-soft)]"
        role="status"
      >
        Loading workflow and economic state…
      </div>
    );
  }

  if (!data) {
    return (
      <div
        className="mt-8 rounded-2xl border border-[var(--red)]/25 bg-[var(--red-soft)] p-6 text-sm font-bold text-[var(--red)]"
        role="alert"
      >
        Lifecycle state is unavailable. Check the API and retry.
      </div>
    );
  }

  const { current, target } = data.workflows;
  const currentApproved = current?.status === "approved";
  const targetApproved = target?.status === "approved";
  const economicsApproved = data.economics?.status === "approved";
  const packetCurrent =
    data.artifacts.length === 7 &&
    new Set(data.artifacts.map((artifact) => artifact.packet_version)).size ===
      1;
  const selectedArtifact =
    data.artifacts.find(
      (artifact) => artifact.artifact_type === selectedArtifactType,
    ) ?? data.artifacts.at(-1);

  return (
    <>
      {notice && (
        <div
          className={`mt-8 rounded-xl border px-4 py-3 text-sm font-bold ${notice.tone === "success" ? "border-[var(--teal)]/25 bg-[var(--teal-soft)] text-[var(--teal)]" : "border-[var(--red)]/25 bg-[var(--red-soft)] text-[var(--red)]"}`}
          role={notice.tone === "error" ? "alert" : "status"}
        >
          {notice.text}
        </div>
      )}

      <section className="mt-14 scroll-mt-6" id="current-workflow">
        <LifecycleHeading
          eyebrow="04 / Process graph"
          title="Current-state workflow"
          detail="A deterministic projection of verified operating assertions. It remains a draft until the FDE approves the sequence and its blockers."
        />
        {!current || current.status === "stale" ? (
          <LifecycleEmpty
            title={
              current?.status === "stale"
                ? "The current workflow is stale."
                : "No current workflow draft yet."
            }
            detail="Construct a fresh draft from the verified Company Operating Model. Entity-only assertions are not invented as process steps."
            button={
              busy === "current-generate"
                ? "Constructing…"
                : "Construct current workflow"
            }
            disabled={busy !== null}
            onClick={() =>
              void runAction(
                "current-generate",
                () => generateCurrentWorkflow(engagementId),
                "A current-state draft was constructed from verified assertions.",
              )
            }
          />
        ) : (
          <WorkflowPanel workflow={current} />
        )}
        {current?.status === "draft" && (
          <div className="surface mt-4 rounded-2xl p-5">
            {blockingContradictions > 0 && (
              <div className="mb-4 rounded-xl border border-[var(--red)]/25 bg-[var(--red-soft)] p-4 text-xs font-bold leading-5 text-[var(--red)]">
                {blockingContradictions} blocking contradiction remains. Resolve
                it above or enter an explicit audited override reason.
              </div>
            )}
            <label className="grid gap-2 text-[0.65rem] font-extrabold uppercase tracking-[0.1em] text-[var(--ink-soft)]">
              Approval note{" "}
              {blockingContradictions > 0
                ? "(required for override)"
                : "(optional)"}
              <textarea
                className="min-h-20 rounded-xl border border-[var(--line)] bg-white px-3 py-2.5 text-xs font-semibold normal-case leading-5 tracking-normal text-[var(--ink)]"
                onChange={(event) => setOverrideReason(event.target.value)}
                value={overrideReason}
              />
            </label>
            <button
              className="mt-4 rounded-full bg-[var(--teal)] px-5 py-3 text-xs font-extrabold text-white disabled:opacity-50"
              disabled={
                busy !== null ||
                (blockingContradictions > 0 &&
                  overrideReason.trim().length === 0)
              }
              onClick={() =>
                void runAction(
                  "current-approve",
                  () =>
                    approveWorkflow(
                      engagementId,
                      current.id,
                      overrideReason || null,
                    ),
                  "The human FDE approved the current-state workflow.",
                )
              }
              type="button"
            >
              {busy === "current-approve"
                ? "Approving…"
                : "Approve current workflow"}
            </button>
          </div>
        )}
      </section>

      <section className="mt-14 scroll-mt-6" id="target-workflow">
        <LifecycleHeading
          eyebrow="05 / Allocation"
          title="Target-state workflow"
          detail="Recommendations are intentionally conservative: preserve existing software, retain material approval authority, and require controls before any AI allocation."
        />
        {!currentApproved ? (
          <LockedStage text="Approve a current-state workflow first." />
        ) : !target || target.status === "stale" ? (
          <LifecycleEmpty
            title={
              target?.status === "stale"
                ? "The target workflow is stale."
                : "No target design yet."
            }
            detail="Copy the approved current workflow into a separate target version with explainable allocation recommendations."
            button={
              busy === "target-generate"
                ? "Designing…"
                : "Design target workflow"
            }
            disabled={busy !== null}
            onClick={() =>
              void runAction(
                "target-generate",
                () => generateTargetWorkflow(engagementId),
                "A separate target workflow was created with conservative allocation recommendations.",
              )
            }
          />
        ) : (
          <WorkflowPanel
            engagementId={engagementId}
            editable={target.status === "draft"}
            onSaved={load}
            workflow={target}
          />
        )}
        {target?.status === "draft" && (
          <button
            className="mt-4 rounded-full bg-[var(--teal)] px-5 py-3 text-xs font-extrabold text-white disabled:opacity-50"
            disabled={busy !== null}
            onClick={() =>
              void runAction(
                "target-approve",
                () => approveWorkflow(engagementId, target.id),
                "The human FDE approved the target workflow and every allocation.",
              )
            }
            type="button"
          >
            {busy === "target-approve"
              ? "Approving…"
              : "Approve target workflow"}
          </button>
        )}
      </section>

      <section className="mt-14 scroll-mt-6" id="economics">
        <LifecycleHeading
          eyebrow="06 / Deterministic case"
          title="Economic model"
          detail="All arithmetic is deterministic. Every input carries an evidence classification; outputs are always labeled calculated."
        />
        {!targetApproved ? (
          <LockedStage text="Approve the target workflow before calculating economics." />
        ) : (
          <div className="mt-5 grid gap-5 xl:grid-cols-[0.8fr_1fr]">
            <form
              className="surface rounded-2xl p-5"
              onSubmit={handleEconomics}
            >
              <div className="flex items-center justify-between gap-4">
                <p className="text-xs font-extrabold uppercase tracking-[0.1em] text-[var(--ink-soft)]">
                  Versioned inputs
                </p>
                <span className="rounded-full bg-[var(--amber-soft)] px-2.5 py-1 text-[0.6rem] font-extrabold uppercase text-[var(--amber)]">
                  Acme defaults are synthetic
                </span>
              </div>
              <div className="mt-4 grid gap-3">
                {economicFields.map((field) => (
                  <div
                    className="grid grid-cols-[1fr_0.65fr] gap-2"
                    key={field.key}
                  >
                    <label className="grid gap-1 text-[0.62rem] font-extrabold uppercase tracking-[0.08em] text-[var(--ink-soft)]">
                      {field.label}
                      <span className="grid grid-cols-[1fr_auto] items-center rounded-lg border border-[var(--line)] bg-white">
                        <input
                          aria-label={`${field.label}, ${field.unit}`}
                          className="min-w-0 bg-transparent px-3 py-2.5 text-xs font-bold normal-case tracking-normal text-[var(--ink)] outline-none"
                          min="0"
                          onChange={(event) =>
                            setEconomicDraft((currentDraft) => ({
                              ...currentDraft,
                              [field.key]: {
                                ...currentDraft[field.key],
                                value: event.target.value,
                              },
                            }))
                          }
                          required
                          step="0.01"
                          type="number"
                          value={economicDraft[field.key].value}
                        />
                        <span className="pr-3 text-[0.58rem] font-bold normal-case tracking-normal text-[var(--ink-soft)]">
                          {field.unit}
                        </span>
                      </span>
                    </label>
                    <label className="grid gap-1 text-[0.62rem] font-extrabold uppercase tracking-[0.08em] text-[var(--ink-soft)]">
                      Evidence
                      <select
                        aria-label={`${field.label} evidence classification`}
                        className="rounded-lg border border-[var(--line)] bg-white px-2 py-2.5 text-xs font-bold normal-case tracking-normal text-[var(--ink)]"
                        onChange={(event) =>
                          setEconomicDraft((currentDraft) => ({
                            ...currentDraft,
                            [field.key]: {
                              ...currentDraft[field.key],
                              classification: event.target
                                .value as EvidenceClassification,
                            },
                          }))
                        }
                        value={economicDraft[field.key].classification}
                      >
                        {classifications.map((classification) => (
                          <option key={classification} value={classification}>
                            {classification}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                ))}
              </div>
              <button
                className="mt-5 rounded-full bg-[var(--ink)] px-5 py-3 text-xs font-extrabold text-white disabled:opacity-50"
                disabled={busy !== null}
                type="submit"
              >
                {busy === "economics-calculate"
                  ? "Calculating…"
                  : data.economics?.status === "draft"
                    ? "Recalculate case"
                    : "Calculate case"}
              </button>
            </form>
            <EconomicResults economicCase={data.economics} />
          </div>
        )}
        {data.economics?.status === "draft" && (
          <button
            className="mt-4 rounded-full bg-[var(--teal)] px-5 py-3 text-xs font-extrabold text-white disabled:opacity-50"
            disabled={busy !== null}
            onClick={() =>
              void runAction(
                "economics-approve",
                () => approveEconomics(engagementId, data.economics!.id),
                "The human FDE approved the deterministic economic case.",
              )
            }
            type="button"
          >
            {busy === "economics-approve"
              ? "Approving…"
              : "Approve economic case"}
          </button>
        )}
      </section>

      <section className="mt-14 scroll-mt-6" id="specification">
        <LifecycleHeading
          eyebrow="07 / Engineering handoff"
          title="Implementation artifact packet"
          detail="Seven version-pinned artifacts separate product intent, architecture, rules, integrations, controls, evaluation, and build detail."
        />
        {!economicsApproved ? (
          <LockedStage text="Approve the economic case before generating the implementation packet." />
        ) : !packetCurrent ? (
          <LifecycleEmpty
            title={
              data.artifacts.length > 0
                ? "The prior artifact set is incomplete."
                : "No current implementation packet."
            }
            detail="Generate seven immutable artifacts from approved upstream state. Coding-agent execution and autonomous remediation are not included."
            button={
              busy === "packet-generate"
                ? "Generating…"
                : "Generate artifact packet"
            }
            disabled={busy !== null}
            onClick={() =>
              void runAction(
                "packet-generate",
                () => generateImplementationPacket(engagementId),
                "A seven-document implementation packet was generated from approved state.",
              )
            }
          />
        ) : selectedArtifact ? (
          <div className="surface mt-5 overflow-hidden rounded-2xl">
            <div className="border-b border-[var(--line)] px-5 py-4">
              <div className="mb-4 flex flex-wrap gap-2" role="tablist">
                {data.artifacts.map((artifact) => (
                  <button
                    aria-selected={
                      artifact.artifact_type === selectedArtifact.artifact_type
                    }
                    className={`rounded-full border px-3 py-2 text-[0.62rem] font-extrabold uppercase tracking-[0.06em] ${artifact.artifact_type === selectedArtifact.artifact_type ? "border-[var(--teal)] bg-[var(--teal-soft)] text-[var(--teal)]" : "border-[var(--line)] text-[var(--ink-soft)]"}`}
                    key={artifact.id}
                    onClick={() =>
                      setSelectedArtifactType(artifact.artifact_type)
                    }
                    role="tab"
                    type="button"
                  >
                    {artifact.artifact_type.replaceAll("_", " ")}
                  </button>
                ))}
              </div>
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                  <p className="text-sm font-extrabold">
                    {selectedArtifact.title}
                  </p>
                  <p className="mt-1 text-[0.62rem] font-bold uppercase tracking-[0.08em] text-[var(--ink-soft)]">
                    Packet {selectedArtifact.packet_version} · Artifact version{" "}
                    {selectedArtifact.version_number} · SHA-256{" "}
                    {selectedArtifact.content_hash.slice(0, 12)}…
                  </p>
                </div>
                <button
                  className="rounded-full border border-[var(--line-strong)] px-4 py-2 text-xs font-extrabold"
                  onClick={() =>
                    void handleCopyArtifact(selectedArtifact.content)
                  }
                  type="button"
                >
                  Copy Markdown
                </button>
              </div>
            </div>
            <pre
              aria-label={`Generated ${selectedArtifact.artifact_type.replaceAll("_", " ")} Markdown`}
              className="max-h-[680px] overflow-auto whitespace-pre-wrap bg-[#102328] p-5 font-mono text-[0.72rem] leading-6 text-[#e7eee9]"
              tabIndex={0}
            >
              {selectedArtifact.content}
            </pre>
          </div>
        ) : null}
      </section>
    </>
  );
}

function LifecycleHeading({
  eyebrow,
  title,
  detail,
}: {
  eyebrow: string;
  title: string;
  detail: string;
}) {
  return (
    <div className="grid gap-3 border-t border-[var(--line-strong)] pt-5 lg:grid-cols-[0.75fr_1fr] lg:items-end">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h2 className="display-font mt-2 text-3xl font-medium tracking-[-0.025em] md:text-4xl">
          {title}
        </h2>
      </div>
      <p className="max-w-2xl text-sm leading-6 text-[var(--ink-soft)]">
        {detail}
      </p>
    </div>
  );
}

function LifecycleEmpty({
  title,
  detail,
  button,
  disabled,
  onClick,
}: {
  title: string;
  detail: string;
  button: string;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <div className="surface mt-5 rounded-2xl p-7">
      <p className="display-font text-2xl font-medium">{title}</p>
      <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--ink-soft)]">
        {detail}
      </p>
      <button
        className="mt-5 rounded-full bg-[var(--ink)] px-5 py-3 text-xs font-extrabold text-white disabled:opacity-50"
        disabled={disabled}
        onClick={onClick}
        type="button"
      >
        {button}
      </button>
    </div>
  );
}

function LockedStage({ text }: { text: string }) {
  return (
    <div className="mt-5 flex items-center gap-3 rounded-2xl border border-[var(--line)] bg-[var(--paper)] p-5 text-sm font-bold text-[var(--ink-soft)]">
      <ShieldIcon className="shrink-0 text-[var(--teal)]" />
      {text}
    </div>
  );
}

function WorkflowPanel({
  workflow,
  engagementId,
  editable = false,
  onSaved,
}: {
  workflow: Workflow;
  engagementId?: string;
  editable?: boolean;
  onSaved?: () => Promise<void>;
}) {
  return (
    <div className="surface mt-5 overflow-hidden rounded-2xl">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--line)] px-5 py-4">
        <div>
          <h3 className="text-sm font-extrabold">{workflow.name}</h3>
          <p className="mt-1 text-[0.62rem] font-bold uppercase tracking-[0.09em] text-[var(--ink-soft)]">
            Version {workflow.version_number} · {workflow.generated_by}{" "}
            generated
          </p>
        </div>
        <span
          className={`rounded-full px-2.5 py-1 text-[0.62rem] font-extrabold uppercase ${workflow.status === "approved" ? "bg-[var(--teal-soft)] text-[var(--teal)]" : "bg-[var(--amber-soft)] text-[var(--amber)]"}`}
        >
          {workflow.status}
        </span>
      </div>
      <div className="divide-y divide-[var(--line)]">
        {workflow.steps.map((step) =>
          editable && engagementId ? (
            <TargetStepEditor
              engagementId={engagementId}
              key={step.id}
              onSaved={onSaved}
              step={step}
              workflowId={workflow.id}
            />
          ) : (
            <WorkflowStepView key={step.id} step={step} />
          ),
        )}
      </div>
    </div>
  );
}

function WorkflowStepView({ step }: { step: WorkflowStep }) {
  return (
    <article className="grid gap-3 p-5 md:grid-cols-[38px_1fr_auto]">
      <span className="display-font grid h-8 w-8 place-items-center rounded-full border border-[var(--line-strong)] text-sm">
        {step.position}
      </span>
      <div>
        <h4 className="text-sm font-extrabold">{step.name}</h4>
        <p className="mt-1 text-xs leading-5 text-[var(--ink-soft)]">
          {step.description}
        </p>
        <div className="mt-3 flex flex-wrap gap-2 text-[0.6rem] font-extrabold uppercase tracking-[0.08em] text-[var(--ink-soft)]">
          {step.actor_label && <span>Actor · {step.actor_label}</span>}
          {step.system_label && <span>System · {step.system_label}</span>}
          {step.source_assertion_id && (
            <span>
              Verified source · {step.source_assertion_id.slice(0, 8)}
            </span>
          )}
        </div>
      </div>
      <span className="h-fit rounded-full bg-[var(--canvas)] px-2.5 py-1 text-[0.6rem] font-extrabold uppercase text-[var(--teal)]">
        {step.allocation.replace("_", " + ")}
      </span>
    </article>
  );
}

function TargetStepEditor({
  engagementId,
  workflowId,
  step,
  onSaved,
}: {
  engagementId: string;
  workflowId: string;
  step: WorkflowStep;
  onSaved?: () => Promise<void>;
}) {
  const [allocation, setAllocation] = useState(step.allocation);
  const [rationale, setRationale] = useState(step.rationale);
  const [controls, setControls] = useState(step.controls.join("; "));
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<string | null>(null);
  async function save() {
    setSaving(true);
    setSaveStatus(null);
    try {
      await updateWorkflowStep(engagementId, workflowId, step.id, {
        allocation,
        rationale,
        controls: controls
          .split(";")
          .map((item) => item.trim())
          .filter(Boolean),
      });
      await onSaved?.();
      setSaveStatus(`Allocation saved for ${step.name}.`);
    } finally {
      setSaving(false);
    }
  }
  return (
    <article className="grid gap-4 p-5 lg:grid-cols-[38px_0.8fr_1fr]">
      <span className="display-font grid h-8 w-8 place-items-center rounded-full border border-[var(--line-strong)] text-sm">
        {step.position}
      </span>
      <div>
        <h4 className="text-sm font-extrabold">{step.name}</h4>
        <p className="mt-1 text-xs leading-5 text-[var(--ink-soft)]">
          {step.description}
        </p>
        <p className="mt-3 text-[0.6rem] font-extrabold uppercase tracking-[0.08em] text-[var(--ink-soft)]">
          {step.actor_label ?? "No actor"}
          {step.system_label ? ` · ${step.system_label}` : ""}
        </p>
      </div>
      <div className="grid gap-2">
        <label className="grid gap-1 text-[0.6rem] font-extrabold uppercase tracking-[0.08em] text-[var(--ink-soft)]">
          Allocation
          <select
            aria-label={`Allocation for ${step.name}`}
            className="rounded-lg border border-[var(--line)] bg-white px-3 py-2 text-xs font-bold normal-case tracking-normal text-[var(--ink)]"
            onChange={(event) =>
              setAllocation(event.target.value as WorkflowStep["allocation"])
            }
            value={allocation}
          >
            <option value="human">Human</option>
            <option value="software">Software</option>
            <option value="ai_human">AI + Human</option>
            <option value="ai">AI</option>
          </select>
        </label>
        <label className="grid gap-1 text-[0.6rem] font-extrabold uppercase tracking-[0.08em] text-[var(--ink-soft)]">
          Rationale
          <textarea
            aria-label={`Rationale for ${step.name}`}
            className="min-h-16 rounded-lg border border-[var(--line)] bg-white px-3 py-2 text-xs font-semibold normal-case leading-5 tracking-normal text-[var(--ink)]"
            onChange={(event) => setRationale(event.target.value)}
            value={rationale}
          />
        </label>
        <label className="grid gap-1 text-[0.6rem] font-extrabold uppercase tracking-[0.08em] text-[var(--ink-soft)]">
          Controls · separate with semicolons
          <input
            aria-label={`Controls for ${step.name}; separate with semicolons`}
            className="rounded-lg border border-[var(--line)] bg-white px-3 py-2 text-xs font-semibold normal-case tracking-normal text-[var(--ink)]"
            onChange={(event) => setControls(event.target.value)}
            value={controls}
          />
        </label>
        <button
          className="justify-self-start rounded-full border border-[var(--line-strong)] px-4 py-2 text-[0.65rem] font-extrabold disabled:opacity-50"
          disabled={saving}
          onClick={() => void save()}
          type="button"
        >
          {saving ? "Saving…" : "Save allocation"}
        </button>
        {saveStatus && (
          <p className="text-xs font-bold text-[var(--teal)]" role="status">
            {saveStatus}
          </p>
        )}
      </div>
    </article>
  );
}

function EconomicResults({
  economicCase,
}: {
  economicCase: EconomicCase | null;
}) {
  if (!economicCase || economicCase.status === "stale")
    return (
      <div className="surface grid min-h-72 place-items-center rounded-2xl p-8 text-center">
        <div>
          <p className="display-font text-2xl font-medium">
            No current calculation.
          </p>
          <p className="mt-2 text-sm text-[var(--ink-soft)]">
            Review the labeled inputs and calculate a reproducible case.
          </p>
        </div>
      </div>
    );
  const scenarioNames = ["low", "base", "high"] as const;
  const hasSensitivityScenarios = scenarioNames.every(
    (scenarioName) => economicCase.scenarios?.[scenarioName],
  );
  return (
    <div className="surface rounded-2xl p-5">
      <div className="flex items-center justify-between">
        <p className="text-xs font-extrabold uppercase tracking-[0.1em] text-[var(--ink-soft)]">
          Calculated outputs
        </p>
        <span
          className={`rounded-full px-2.5 py-1 text-[0.6rem] font-extrabold uppercase ${economicCase.status === "approved" ? "bg-[var(--teal-soft)] text-[var(--teal)]" : "bg-[var(--amber-soft)] text-[var(--amber)]"}`}
        >
          {economicCase.status}
        </span>
      </div>
      {hasSensitivityScenarios ? (
        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          {scenarioNames.map((scenarioName) => {
            const scenario = economicCase.scenarios[scenarioName];
            const netBenefit = scenario.outputs.annual_net_benefit;
            const payback = scenario.outputs.payback_months;
            return (
              <article
                className={`rounded-xl border p-4 ${scenarioName === "base" ? "border-[var(--teal)] bg-[var(--teal-soft)]" : "border-[var(--line)] bg-white"}`}
                key={scenarioName}
              >
                <p className="text-[0.62rem] font-extrabold uppercase tracking-[0.08em] text-[var(--ink-soft)]">
                  {scenario.label} scenario
                </p>
                <p className="display-font mt-2 text-xl font-medium">
                  {formatEconomicValue(netBenefit.value, netBenefit.unit)}
                </p>
                <p className="mt-1 text-[0.62rem] font-bold text-[var(--ink-soft)]">
                  {payback.value
                    ? `${formatEconomicValue(payback.value, payback.unit)} payback`
                    : "No positive payback"}
                </p>
                <p className="mt-3 text-[0.62rem] leading-5 text-[var(--ink-soft)]">
                  {scenario.description}
                </p>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="mt-4 rounded-xl border border-[var(--amber)]/25 bg-[var(--amber-soft)] p-4 text-xs font-bold leading-5 text-[var(--amber)]">
          This case predates sensitivity scenarios. Recalculate it before
          approval or handoff.
        </div>
      )}
      <p className="mt-5 text-[0.62rem] font-extrabold uppercase tracking-[0.1em] text-[var(--ink-soft)]">
        Base scenario detail
      </p>
      <div className="mt-4 grid gap-3">
        {Object.entries(economicCase.outputs).map(([key, output]) => (
          <div
            className="rounded-xl border border-[var(--line)] bg-white p-4"
            key={key}
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-[0.62rem] font-extrabold uppercase tracking-[0.08em] text-[var(--ink-soft)]">
                  {key.replaceAll("_", " ")}
                </p>
                <p className="display-font mt-1 text-2xl font-medium">
                  {formatEconomicValue(output.value, output.unit)}
                </p>
              </div>
              <span className="rounded-full bg-[var(--teal-soft)] px-2 py-1 text-[0.58rem] font-extrabold uppercase text-[var(--teal)]">
                calculated
              </span>
            </div>
            <p className="mt-3 text-[0.62rem] leading-5 text-[var(--ink-soft)]">
              {output.formula}
            </p>
          </div>
        ))}
      </div>
      <p className="mt-4 flex items-center gap-2 text-[0.62rem] font-bold text-[var(--ink-soft)]">
        <CheckIcon className="text-[var(--teal)]" /> Formula{" "}
        {economicCase.formula_version}
      </p>
    </div>
  );
}

function formatEconomicValue(value: string | null, unit: string) {
  if (value === null) return "No positive payback";
  const number = Number(value);
  if (unit.startsWith("USD"))
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 0,
    }).format(number);
  return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(number)} ${unit}`;
}
