"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import { CheckIcon, ShieldIcon } from "@/components/icons";
import { getDeliveryScorecard, recordEngagementAssessment } from "@/lib/api";
import type {
  AssessmentOutcome,
  AssessmentPerspective,
  DeliveryMethod,
  DeliveryScorecard,
} from "@/lib/types";

export function DeliveryEvaluationWorkspace({
  engagementId,
  lifecycleVersion,
  onReady,
}: {
  engagementId: string;
  lifecycleVersion: string;
  onReady: (ready: boolean) => void;
}) {
  const [scorecard, setScorecard] = useState<DeliveryScorecard | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState<{
    tone: "success" | "error";
    text: string;
  } | null>(null);

  const load = useCallback(async () => {
    const current = await getDeliveryScorecard(engagementId);
    setScorecard(current);
    onReady(current.assessments.length > 0);
  }, [engagementId, onReady]);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      load()
        .catch((reason: unknown) =>
          setNotice({
            tone: "error",
            text:
              reason instanceof Error
                ? reason.message
                : "The delivery scorecard could not be loaded.",
          }),
        )
        .finally(() => setLoading(false));
    }, 0);
    return () => window.clearTimeout(timeout);
  }, [load, lifecycleVersion]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setNotice(null);
    const form = new FormData(event.currentTarget);
    try {
      await recordEngagementAssessment(engagementId, {
        delivery_method: String(form.get("delivery_method")) as DeliveryMethod,
        perspective: String(form.get("perspective")) as AssessmentPerspective,
        outcome: String(form.get("outcome")) as AssessmentOutcome,
        duration_minutes: Number(form.get("duration_minutes")),
        usefulness_score: Number(form.get("usefulness_score")),
        clarification_count: Number(form.get("clarification_count")),
        rework_count: Number(form.get("rework_count")),
        workaround_count: Number(form.get("workaround_count")),
        trust_failure_count: Number(form.get("trust_failure_count")),
        notes: String(form.get("notes")).trim() || null,
      });
      await load();
      setNotice({
        tone: "success",
        text: "Assessment saved. Structured measures were audited; free-text notes were excluded from audit and event payloads.",
      });
    } catch (reason) {
      setNotice({
        tone: "error",
        text:
          reason instanceof Error
            ? reason.message
            : "The assessment could not be recorded.",
      });
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <div
        aria-live="polite"
        className="surface mt-8 rounded-2xl p-8 text-sm font-bold text-[var(--ink-soft)]"
        role="status"
      >
        Loading delivery scorecard…
      </div>
    );
  }

  if (!scorecard) {
    return (
      <section
        className="mt-14 rounded-2xl border border-[var(--red)]/25 bg-[var(--red-soft)] p-6 text-sm font-bold text-[var(--red)]"
        id="evaluation"
        role="alert"
      >
        Delivery evaluation is unavailable. Check the API and retry.
      </section>
    );
  }

  return (
    <section className="mt-14 scroll-mt-6" id="evaluation">
      <div className="grid gap-3 lg:grid-cols-[1fr_0.72fr] lg:items-end">
        <div>
          <p className="eyebrow">08 / Delivery proof</p>
          <h2 className="display-font mt-3 text-3xl font-medium md:text-4xl">
            Outcome and efficiency scorecard
          </h2>
        </div>
        <p className="text-sm leading-6 text-[var(--ink-soft)]">
          Measure time, rework, trust failures, and token use with absolute
          values. Comparative claims stay locked until both cohorts meet the
          evaluation threshold.
        </p>
      </div>

      {notice && (
        <div
          className={
            "mt-5 rounded-xl border px-4 py-3 text-sm font-bold " +
            (notice.tone === "success"
              ? "border-[var(--teal)]/25 bg-[var(--teal-soft)] text-[var(--teal)]"
              : "border-[var(--red)]/25 bg-[var(--red-soft)] text-[var(--red)]")
          }
          role={notice.tone === "error" ? "alert" : "status"}
        >
          {notice.text}
        </div>
      )}

      <div className="mt-5 grid gap-5 xl:grid-cols-[0.82fr_1.18fr]">
        <div className="grid content-start gap-5">
          <div className="surface rounded-2xl p-5">
            <div className="flex items-center justify-between gap-4">
              <p className="text-xs font-extrabold uppercase tracking-[0.1em] text-[var(--ink-soft)]">
                Objective state
              </p>
              <span
                className={
                  "rounded-full px-2.5 py-1 text-[0.62rem] font-extrabold uppercase tracking-[0.08em] " +
                  (scorecard.packet.complete
                    ? "bg-[var(--teal-soft)] text-[var(--teal)]"
                    : "bg-[var(--amber-soft)] text-[var(--amber)]")
                }
              >
                {scorecard.packet.complete ? "Packet complete" : "In progress"}
              </span>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3">
              <ScoreMetric
                label="Material claims"
                value={scorecard.claims.material_accepted}
              />
              <ScoreMetric
                label="Artifacts"
                value={
                  String(scorecard.packet.artifact_count) +
                  "/" +
                  String(scorecard.packet.expected_artifact_count)
                }
              />
              <ScoreMetric
                label="Provider tokens"
                value={scorecard.provider.total_tokens.toLocaleString()}
              />
              <ScoreMetric
                label="Tokens / claim"
                value={
                  scorecard.provider.tokens_per_accepted_material_claim ?? "—"
                }
              />
            </div>
            <div className="mt-5 grid gap-2">
              {Object.entries(scorecard.milestones).map(([label, complete]) => (
                <div
                  className="flex items-center justify-between gap-4 rounded-xl border border-[var(--line)] bg-white px-3.5 py-3"
                  key={label}
                >
                  <span className="text-xs font-bold capitalize text-[var(--ink-soft)]">
                    {label.replaceAll("_", " ")}
                  </span>
                  <span
                    className={
                      "grid h-6 w-6 place-items-center rounded-full " +
                      (complete
                        ? "bg-[var(--teal)] text-white"
                        : "border border-[var(--line-strong)] text-[var(--ink-soft)]")
                    }
                  >
                    {complete ? <CheckIcon className="h-3.5 w-3.5" /> : "—"}
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-2xl border border-[var(--line)] bg-[var(--ink)] p-5 text-white">
            <div className="flex items-center gap-2 text-xs font-extrabold uppercase tracking-[0.1em] text-[#9dc8c2]">
              <ShieldIcon className="h-4 w-4" /> Claim discipline
            </div>
            <p className="mt-3 text-sm leading-6 text-white/70">
              Zero local fixture tokens means no model call occurred—not a
              production cost claim. Bedrock runs will populate provider, model,
              token, and latency fields from the extraction ledger.
            </p>
          </div>
        </div>

        <div className="surface rounded-2xl p-5 md:p-6">
          <p className="text-xs font-extrabold uppercase tracking-[0.1em] text-[var(--ink-soft)]">
            Record an evaluator observation
          </p>
          <p className="mt-2 text-xs leading-5 text-[var(--ink-soft)]">
            One current record is kept per evaluator, method, and perspective;
            every update leaves an immutable audit entry.
          </p>
          <form className="mt-5 grid gap-4" onSubmit={handleSubmit}>
            <div className="grid gap-4 md:grid-cols-3">
              <AssessmentSelect
                label="Delivery method"
                name="delivery_method"
                options={[
                  ["ai_fde", "Factory Engineer"],
                  ["conventional", "Conventional"],
                ]}
              />
              <AssessmentSelect
                label="Perspective"
                name="perspective"
                options={[
                  ["operator", "Operator"],
                  ["engineering", "Engineering"],
                ]}
              />
              <AssessmentSelect
                label="Outcome"
                name="outcome"
                options={[
                  ["completed", "Completed"],
                  ["blocked", "Blocked"],
                  ["abandoned", "Abandoned"],
                ]}
              />
            </div>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              <AssessmentNumber
                label="Duration (minutes)"
                min={1}
                name="duration_minutes"
                value={90}
              />
              <AssessmentNumber
                label="Usefulness (1–5)"
                max={5}
                min={1}
                name="usefulness_score"
                value={4}
              />
              <AssessmentNumber
                label="Clarifications"
                min={0}
                name="clarification_count"
                value={0}
              />
              <AssessmentNumber
                label="Rework events"
                min={0}
                name="rework_count"
                value={0}
              />
              <AssessmentNumber
                label="Workarounds"
                min={0}
                name="workaround_count"
                value={0}
              />
              <AssessmentNumber
                label="Trust failures"
                min={0}
                name="trust_failure_count"
                value={0}
              />
            </div>
            <label className="grid gap-1.5 text-[0.65rem] font-extrabold uppercase tracking-[0.1em] text-[var(--ink-soft)]">
              Notes (excluded from audit payloads)
              <textarea
                className="min-h-24 resize-y rounded-lg border border-[var(--line)] bg-white px-3 py-2.5 text-xs font-semibold leading-5 normal-case tracking-normal text-[var(--ink)]"
                maxLength={2000}
                name="notes"
              />
            </label>
            <div className="flex items-center justify-between gap-4">
              <p className="text-xs font-semibold text-[var(--ink-soft)]">
                {scorecard.assessments.length === 0
                  ? "No evaluator observations yet."
                  : String(scorecard.assessments.length) +
                    " current observation" +
                    (scorecard.assessments.length === 1 ? "." : "s.")}
              </p>
              <button
                className="rounded-full bg-[var(--teal)] px-5 py-3 text-sm font-extrabold text-white disabled:cursor-wait disabled:opacity-60"
                disabled={submitting}
                type="submit"
              >
                {submitting ? "Recording…" : "Record assessment"}
              </button>
            </div>
          </form>

          {scorecard.assessments.length > 0 && (
            <div className="mt-6 border-t border-[var(--line)] pt-5">
              <p className="text-xs font-extrabold uppercase tracking-[0.1em] text-[var(--ink-soft)]">
                Current observations
              </p>
              <div className="mt-3 grid gap-2">
                {scorecard.assessments.map((assessment) => (
                  <div
                    className="grid gap-2 rounded-xl border border-[var(--line)] bg-white p-3.5 sm:grid-cols-[1fr_auto] sm:items-center"
                    key={assessment.id}
                  >
                    <div>
                      <p className="text-xs font-extrabold">
                        {assessment.delivery_method === "ai_fde"
                          ? "Factory Engineer"
                          : "Conventional"}
                        {" · "}
                        {assessment.perspective} · {assessment.outcome}
                      </p>
                      <p className="mt-1 text-[0.65rem] font-semibold text-[var(--ink-soft)]">
                        {assessment.duration_minutes} min · usefulness{" "}
                        {assessment.usefulness_score}/5 · rework{" "}
                        {assessment.rework_count} · trust failures{" "}
                        {assessment.trust_failure_count}
                      </p>
                    </div>
                    <time className="text-[0.62rem] font-bold text-[var(--ink-soft)]">
                      {new Date(assessment.updated_at).toLocaleDateString()}
                    </time>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function ScoreMetric({
  label,
  value,
}: {
  label: string;
  value: number | string;
}) {
  return (
    <div className="rounded-xl border border-[var(--line)] bg-white p-3.5">
      <p className="display-font text-2xl font-medium">{value}</p>
      <p className="mt-1 text-[0.6rem] font-extrabold uppercase tracking-[0.09em] text-[var(--ink-soft)]">
        {label}
      </p>
    </div>
  );
}

function AssessmentSelect({
  label,
  name,
  options,
}: {
  label: string;
  name: string;
  options: Array<[string, string]>;
}) {
  return (
    <label className="grid gap-1.5 text-[0.65rem] font-extrabold uppercase tracking-[0.1em] text-[var(--ink-soft)]">
      {label}
      <select
        className="rounded-lg border border-[var(--line)] bg-white px-3 py-2.5 text-xs font-semibold normal-case tracking-normal text-[var(--ink)]"
        name={name}
      >
        {options.map(([value, optionLabel]) => (
          <option key={value} value={value}>
            {optionLabel}
          </option>
        ))}
      </select>
    </label>
  );
}

function AssessmentNumber({
  label,
  min,
  max = 10000,
  name,
  value,
}: {
  label: string;
  min: number;
  max?: number;
  name: string;
  value: number;
}) {
  return (
    <label className="grid gap-1.5 text-[0.65rem] font-extrabold uppercase tracking-[0.1em] text-[var(--ink-soft)]">
      {label}
      <input
        className="rounded-lg border border-[var(--line)] bg-white px-3 py-2.5 text-xs font-semibold normal-case tracking-normal text-[var(--ink)]"
        defaultValue={value}
        max={max}
        min={min}
        name={name}
        required
        type="number"
      />
    </label>
  );
}
