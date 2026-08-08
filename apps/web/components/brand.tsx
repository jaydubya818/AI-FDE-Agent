import Link from "next/link";

export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <Link aria-label="AI-FDE home" className="inline-flex items-center gap-3 text-[var(--ink)] no-underline" href="/">
      <span className="grid h-9 w-9 place-items-center rounded-full border border-[var(--ink)] text-xs font-extrabold tracking-[-0.05em]">
        AF
      </span>
      {!compact && (
        <span>
          <span className="block text-sm font-extrabold tracking-[-0.02em]">AI-FDE</span>
          <span className="block text-[0.6rem] font-bold uppercase tracking-[0.16em] text-[var(--ink-soft)]">Operator Cockpit</span>
        </span>
      )}
    </Link>
  );
}
