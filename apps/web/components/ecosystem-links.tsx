import { ECOSYSTEM_LINKS } from "@/lib/product";

export function EcosystemLinks({ compact = false }: { compact?: boolean }) {
  return (
    <nav
      aria-label="FDLC ecosystem"
      className={compact ? undefined : "w-full lg:w-auto"}
    >
      <ul
        className={
          compact
            ? "flex flex-wrap gap-x-3 gap-y-1"
            : "flex flex-wrap items-center gap-x-4 gap-y-1"
        }
      >
        {ECOSYSTEM_LINKS.map((link) => (
          <li key={link.key}>
            <a
              className="text-[0.68rem] font-extrabold uppercase tracking-[0.08em] text-[var(--ink-soft)] no-underline transition hover:text-[var(--ink)]"
              href={link.href}
              rel="noreferrer"
              target="_blank"
            >
              {link.label}
              <span aria-hidden="true"> ↗</span>
              <span className="sr-only"> (opens in a new tab)</span>
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
