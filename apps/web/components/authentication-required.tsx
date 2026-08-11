import { Brand } from "@/components/brand";
import { ArrowIcon, ShieldIcon } from "@/components/icons";
import { getAuthLoginUrl } from "@/lib/api";

export function AuthenticationRequired({ returnTo }: { returnTo: string }) {
  return (
    <main
      className="min-h-screen px-5 py-5 md:px-10 md:py-8"
      id="main-content"
      tabIndex={-1}
    >
      <header className="mx-auto flex max-w-[1120px] items-center justify-between">
        <Brand />
        <div className="inline-flex items-center gap-2 rounded-full border border-[var(--line)] bg-[var(--paper)] px-4 py-2 text-xs font-bold text-[var(--ink-soft)]">
          <ShieldIcon /> Protected workspace
        </div>
      </header>

      <section className="mx-auto grid min-h-[calc(100vh-7rem)] max-w-[1120px] items-center py-16">
        <div className="surface overflow-hidden rounded-[1.75rem]">
          <div className="grid lg:grid-cols-[1.15fr_0.85fr]">
            <div className="p-8 md:p-14 lg:p-16">
              <p className="eyebrow">Secure operator access</p>
              <h1 className="display-font mt-5 max-w-2xl text-5xl font-medium leading-[0.98] tracking-[-0.04em] md:text-6xl">
                Return to the verified operating state.
              </h1>
              <p className="mt-6 max-w-xl text-base leading-7 text-[var(--ink-soft)]">
                Authenticate as an approved Forward Deployed Engineer. Identity
                establishes the operator; AI-FDE&apos;s engagement memberships
                remain the authority for every action.
              </p>
              <a
                className="mt-9 inline-flex items-center gap-3 rounded-full bg-[var(--ink)] px-6 py-3.5 text-sm font-extrabold text-white no-underline transition hover:-translate-y-0.5 hover:shadow-[var(--shadow)]"
                href={getAuthLoginUrl(returnTo)}
              >
                Continue with Auth0 <ArrowIcon />
              </a>
            </div>

            <div className="border-t border-[var(--line)] bg-[var(--teal-soft)]/55 p-8 md:p-12 lg:border-l lg:border-t-0">
              <p className="text-xs font-extrabold uppercase tracking-[0.14em] text-[var(--teal)]">
                Trust boundary
              </p>
              <div className="mt-8 grid gap-7">
                <TrustPoint
                  number="01"
                  title="Provider tokens stay server-side"
                  detail="The browser receives only a random, HTTP-only AI-FDE session cookie."
                />
                <TrustPoint
                  number="02"
                  title="Access remains engagement-scoped"
                  detail="Application roles and PostgreSQL row policies independently enforce isolation."
                />
                <TrustPoint
                  number="03"
                  title="Human authority is preserved"
                  detail="Authentication does not bypass verification or approval stage gates."
                />
              </div>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}

function TrustPoint({
  number,
  title,
  detail,
}: {
  number: string;
  title: string;
  detail: string;
}) {
  return (
    <div className="grid grid-cols-[2rem_1fr] gap-3">
      <span className="grid h-8 w-8 place-items-center rounded-full border border-[var(--teal)]/30 text-[0.62rem] font-extrabold text-[var(--teal)]">
        {number}
      </span>
      <div>
        <p className="text-sm font-extrabold tracking-[-0.01em]">{title}</p>
        <p className="mt-1.5 text-xs leading-5 text-[var(--ink-soft)]">
          {detail}
        </p>
      </div>
    </div>
  );
}
