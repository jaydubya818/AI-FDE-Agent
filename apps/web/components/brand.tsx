import Link from "next/link";

import { PRODUCT } from "@/lib/product";

export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <Link
      aria-label={`${PRODUCT.shortName} home`}
      className="inline-flex items-center gap-3 text-[var(--ink)] no-underline"
      href="/"
    >
      <span className="grid h-9 w-9 place-items-center rounded-full border border-[var(--fdlc-green)] text-[0.55rem] font-extrabold tracking-[-0.04em] text-[var(--fdlc-green)]">
        FDLC
      </span>
      {!compact && (
        <span>
          <span className="block text-sm font-extrabold tracking-[-0.02em]">
            {PRODUCT.shortName}
          </span>
          <span className="block text-[0.6rem] font-bold uppercase tracking-[0.16em] text-[var(--ink-soft)]">
            Engagement cockpit
          </span>
        </span>
      )}
    </Link>
  );
}
