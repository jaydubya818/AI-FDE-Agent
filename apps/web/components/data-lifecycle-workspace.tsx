"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import { CheckIcon, FileIcon, ShieldIcon } from "@/components/icons";
import {
  deleteEngagementData,
  downloadEngagementExport,
  getEngagementDataLifecycle,
  updateEngagementRetention,
} from "@/lib/api";
import type {
  Engagement,
  EngagementDataLifecycle,
  EngagementDeletionReceipt,
} from "@/lib/types";

type Notice = { tone: "success" | "error"; text: string } | null;

function formatDate(value: string | null) {
  if (!value) return "Not scheduled";
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

export function DataLifecycleWorkspace({
  engagement,
  onDeleted,
  onReady,
}: {
  engagement: Engagement;
  onDeleted: (receipt: EngagementDeletionReceipt) => void;
  onReady: (ready: boolean) => void;
}) {
  const [lifecycle, setLifecycle] = useState<EngagementDataLifecycle | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<"retention" | "export" | "delete" | null>(
    null,
  );
  const [notice, setNotice] = useState<Notice>(null);
  const [retentionValue, setRetentionValue] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await getEngagementDataLifecycle(engagement.id);
      setLifecycle(result);
      onReady(result.export_current);
    } catch (reason) {
      setNotice({
        tone: "error",
        text:
          reason instanceof Error
            ? reason.message
            : "The data lifecycle state could not be loaded.",
      });
      onReady(false);
    } finally {
      setLoading(false);
    }
  }, [engagement.id, onReady]);

  useEffect(() => {
    const timeout = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timeout);
  }, [load]);

  async function handleRetention(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!retentionValue) return;
    setBusy("retention");
    setNotice(null);
    try {
      await updateEngagementRetention(
        engagement.id,
        new Date(retentionValue).toISOString(),
      );
      setNotice({
        tone: "success",
        text: "The retention deadline was recorded. V1 permits extensions, not reductions.",
      });
      setRetentionValue("");
      await load();
    } catch (reason) {
      setNotice({
        tone: "error",
        text:
          reason instanceof Error
            ? reason.message
            : "The retention deadline could not be saved.",
      });
    } finally {
      setBusy(null);
    }
  }

  async function handleExport() {
    setBusy("export");
    setNotice(null);
    try {
      const exported = await downloadEngagementExport(engagement.id);
      const url = URL.createObjectURL(exported.blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = exported.filename;
      document.body.append(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setNotice({
        tone: "success",
        text: "A current portability archive was verified and downloaded.",
      });
      await load();
    } catch (reason) {
      setNotice({
        tone: "error",
        text:
          reason instanceof Error
            ? reason.message
            : "The portability export could not be generated.",
      });
    } finally {
      setBusy(null);
    }
  }

  async function handleDelete() {
    if (!lifecycle?.latest_export) return;
    setBusy("delete");
    setNotice(null);
    try {
      const receipt = await deleteEngagementData(engagement.id, {
        export_id: lifecycle.latest_export.id,
        confirmation_name: confirmation,
      });
      onDeleted(receipt);
    } catch (reason) {
      setNotice({
        tone: "error",
        text:
          reason instanceof Error
            ? reason.message
            : "The engagement could not be deleted.",
      });
      await load();
      setBusy(null);
    }
  }

  const owner = lifecycle?.membership_role === "owner";
  const confirmationMatches = confirmation === engagement.name;

  return (
    <section
      aria-busy={loading}
      aria-labelledby="data-lifecycle-heading"
      className="mt-14 scroll-mt-6"
      id="data-lifecycle"
    >
      <div className="grid gap-3 border-t border-[var(--line-strong)] pt-5 lg:grid-cols-[0.75fr_1fr] lg:items-end">
        <div>
          <p className="eyebrow">08 / Data stewardship</p>
          <h2
            className="display-font mt-2 text-3xl font-medium tracking-[-0.025em] md:text-4xl"
            id="data-lifecycle-heading"
          >
            Retention, export & deletion
          </h2>
        </div>
        <p className="max-w-2xl text-sm leading-6 text-[var(--ink-soft)]">
          Portability precedes destruction. A current export is required before
          customer content can be removed, while a content-free receipt survives
          the engagement.
        </p>
      </div>

      {notice && (
        <div
          className={`mt-5 rounded-xl border px-4 py-3 text-sm font-bold ${notice.tone === "success" ? "border-[var(--teal)]/25 bg-[var(--teal-soft)] text-[var(--teal)]" : "border-[var(--red)]/25 bg-[var(--red-soft)] text-[var(--red)]"}`}
          role={notice.tone === "error" ? "alert" : "status"}
        >
          {notice.text}
        </div>
      )}

      {loading || !lifecycle ? (
        <div
          aria-live="polite"
          className="surface mt-5 rounded-2xl p-8"
          role="status"
        >
          <span className="sr-only">Loading data lifecycle state…</span>
          <span
            aria-hidden="true"
            className="block h-2 w-40 animate-pulse rounded-full bg-[var(--line)]"
          />
          <span
            aria-hidden="true"
            className="mt-4 block h-2 w-2/3 animate-pulse rounded-full bg-[var(--line)]"
          />
        </div>
      ) : (
        <div className="mt-5 grid gap-5 xl:grid-cols-[0.8fr_1.2fr]">
          <div className="grid content-start gap-5">
            <article className="surface rounded-2xl p-5 md:p-6">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-[0.65rem] font-extrabold uppercase tracking-[0.12em] text-[var(--teal)]">
                    Retention boundary
                  </p>
                  <h3 className="display-font mt-2 text-2xl font-medium">
                    {formatDate(lifecycle.retention_expires_at)}
                  </h3>
                </div>
                <ShieldIcon className="h-6 w-6 text-[var(--teal)]" />
              </div>
              <p className="mt-4 text-xs leading-5 text-[var(--ink-soft)]">
                AI-FDE does not assume a contractual retention period. Once a
                deadline is recorded, V1 can extend it but cannot silently
                shorten it.
              </p>
              {owner ? (
                <form className="mt-5 grid gap-3" onSubmit={handleRetention}>
                  <label className="grid gap-2 text-[0.62rem] font-extrabold uppercase tracking-[0.1em] text-[var(--ink-soft)]">
                    Retain until
                    <input
                      className="rounded-xl border border-[var(--line)] bg-white px-3 py-3 text-xs font-bold normal-case tracking-normal text-[var(--ink)]"
                      disabled={busy !== null || lifecycle.status !== "active"}
                      min={new Date().toISOString().slice(0, 16)}
                      onChange={(event) =>
                        setRetentionValue(event.target.value)
                      }
                      required
                      type="datetime-local"
                      value={retentionValue}
                    />
                  </label>
                  <button
                    className="justify-self-start rounded-full border border-[var(--line-strong)] px-4 py-2.5 text-xs font-extrabold disabled:opacity-50"
                    disabled={busy !== null || !retentionValue}
                    type="submit"
                  >
                    {busy === "retention" ? "Recording…" : "Record deadline"}
                  </button>
                </form>
              ) : (
                <p className="mt-5 rounded-xl bg-[var(--canvas)] p-3 text-xs font-bold text-[var(--ink-soft)]">
                  Only the engagement owner can change data policy.
                </p>
              )}
            </article>

            <article className="surface rounded-2xl p-5 md:p-6">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-[0.65rem] font-extrabold uppercase tracking-[0.12em] text-[var(--teal)]">
                    Portability checkpoint
                  </p>
                  <h3 className="display-font mt-2 text-2xl font-medium">
                    {lifecycle.export_current
                      ? "Current export verified"
                      : lifecycle.latest_export
                        ? "Export is stale"
                        : "No export yet"}
                  </h3>
                </div>
                <FileIcon className="h-6 w-6 text-[var(--teal)]" />
              </div>
              {lifecycle.latest_export && (
                <dl className="mt-5 grid grid-cols-2 gap-3 border-y border-[var(--line)] py-4 text-xs">
                  <div>
                    <dt className="font-bold text-[var(--ink-soft)]">
                      Archive
                    </dt>
                    <dd className="mt-1 font-extrabold">
                      {formatBytes(lifecycle.latest_export.byte_count)}
                    </dd>
                  </div>
                  <div>
                    <dt className="font-bold text-[var(--ink-soft)]">
                      Contents
                    </dt>
                    <dd className="mt-1 font-extrabold">
                      {lifecycle.latest_export.record_count} records ·{" "}
                      {lifecycle.latest_export.evidence_object_count} files
                    </dd>
                  </div>
                  <div className="col-span-2">
                    <dt className="font-bold text-[var(--ink-soft)]">
                      SHA-256
                    </dt>
                    <dd className="mt-1 break-all font-mono text-[0.64rem] font-bold">
                      {lifecycle.latest_export.archive_hash}
                    </dd>
                  </div>
                </dl>
              )}
              <p className="mt-4 text-xs leading-5 text-[var(--ink-soft)]">
                ZIP includes JSON and YAML state, Markdown specifications, audit
                history, and original evidence with hash verification.
              </p>
              {owner && (
                <button
                  className="mt-5 rounded-full bg-[var(--ink)] px-4 py-2.5 text-xs font-extrabold text-white disabled:cursor-wait disabled:opacity-50"
                  disabled={busy !== null || lifecycle.status !== "active"}
                  onClick={() => void handleExport()}
                  type="button"
                >
                  {busy === "export"
                    ? "Verifying archive…"
                    : lifecycle.export_current
                      ? "Download fresh export"
                      : "Generate & download export"}
                </button>
              )}
            </article>
          </div>

          <article className="overflow-hidden rounded-2xl border border-[var(--red)]/25 bg-[var(--paper)]">
            <div className="border-b border-[var(--red)]/20 bg-[var(--red-soft)] px-5 py-5 md:px-7">
              <p className="text-[0.65rem] font-extrabold uppercase tracking-[0.12em] text-[var(--red)]">
                Permanent action
              </p>
              <h3 className="display-font mt-2 text-3xl font-medium">
                Delete engagement data
              </h3>
              <p className="mt-3 max-w-2xl text-xs leading-5 text-[var(--red)]">
                Removes the engagement, structured model, workflows, economics,
                artifacts, audit detail, and evidence objects. Only a
                content-free receipt remains.
              </p>
            </div>

            <div className="p-5 md:p-7">
              <ol
                className="grid gap-3 text-xs font-bold text-[var(--ink-soft)]"
                id="deletion-gates"
              >
                <Gate
                  complete={lifecycle.export_current}
                  text="A current portability export has been downloaded"
                />
                <Gate
                  complete={!lifecycle.retention_blocked}
                  text={
                    lifecycle.retention_blocked
                      ? `Retention remains active until ${formatDate(lifecycle.retention_expires_at)}`
                      : "No active retention deadline blocks deletion"
                  }
                />
                <Gate
                  complete={owner}
                  text="The authenticated operator is the engagement owner"
                />
              </ol>

              {lifecycle.status === "deletion_failed" && (
                <div className="mt-5 rounded-xl border border-[var(--red)]/20 bg-[var(--red-soft)] p-4 text-xs font-bold leading-5 text-[var(--red)]">
                  A prior deletion attempt failed. Business writes remain
                  blocked; retry uses the same current export and idempotent
                  object removal.
                </div>
              )}

              {owner && (
                <div className="mt-6 grid gap-4 border-t border-[var(--line)] pt-5">
                  <label className="grid gap-2 text-[0.62rem] font-extrabold uppercase tracking-[0.1em] text-[var(--ink-soft)]">
                    Type the engagement name to confirm
                    <input
                      aria-describedby="deletion-gates"
                      autoComplete="off"
                      className="rounded-xl border border-[var(--line)] bg-white px-3 py-3 text-xs font-bold normal-case tracking-normal text-[var(--ink)]"
                      disabled={busy !== null || !lifecycle.can_delete}
                      onChange={(event) => setConfirmation(event.target.value)}
                      placeholder={engagement.name}
                      value={confirmation}
                    />
                  </label>
                  <label className="flex items-start gap-3 text-xs font-bold leading-5 text-[var(--ink-soft)]">
                    <input
                      checked={acknowledged}
                      className="mt-1 h-4 w-4 accent-[var(--red)]"
                      disabled={busy !== null || !lifecycle.can_delete}
                      onChange={(event) =>
                        setAcknowledged(event.target.checked)
                      }
                      type="checkbox"
                    />
                    I understand that AI-FDE cannot restore the deleted customer
                    content from its databases or object storage.
                  </label>
                  <button
                    className="justify-self-start rounded-full bg-[var(--red)] px-5 py-3 text-xs font-extrabold text-white disabled:cursor-not-allowed disabled:opacity-40"
                    disabled={
                      busy !== null ||
                      !lifecycle.can_delete ||
                      !confirmationMatches ||
                      !acknowledged
                    }
                    onClick={() => void handleDelete()}
                    type="button"
                  >
                    {busy === "delete"
                      ? "Deleting verified data…"
                      : lifecycle.status === "deletion_failed"
                        ? "Retry permanent deletion"
                        : "Permanently delete engagement"}
                  </button>
                </div>
              )}
            </div>
          </article>
        </div>
      )}
    </section>
  );
}

function Gate({ complete, text }: { complete: boolean; text: string }) {
  return (
    <li className="flex items-start gap-3">
      <span
        className={`grid h-6 w-6 shrink-0 place-items-center rounded-full border ${complete ? "border-[var(--teal)] bg-[var(--teal)] text-white" : "border-[var(--line-strong)] text-[var(--ink-soft)]"}`}
      >
        {complete ? <CheckIcon className="h-3.5 w-3.5" /> : "—"}
      </span>
      <span className="pt-0.5">{text}</span>
    </li>
  );
}
