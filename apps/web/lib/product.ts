export const PRODUCT = {
  name: "FDLC Factory Deployed Engineer",
  shortName: "Factory Engineer",
  description:
    "The evidence-backed operating workspace that turns customer reality into approved software-factory deployment intent.",
  conciseDescription:
    "Turn enterprise reality into a deployable software factory.",
  northStar:
    "Make deploying an AI software factory faster without sacrificing evidence, verification, economics, security, accountability, or human authority.",
} as const;

export const ECOSYSTEM_LINKS = [
  {
    key: "framework",
    label: "Framework",
    href: "https://fdlc.ai/framework",
  },
  {
    key: "guide",
    label: "Guide",
    href: "https://ai-software-factory-mastery.vercel.app",
  },
  {
    key: "mission-control",
    label: "Mission Control",
    href: "https://fdlc.ai/mission-control",
  },
] as const;

const GUIDE_BASE_URL = "https://ai-software-factory-mastery.vercel.app";

export const GUIDE_LINKS = {
  "autonomy.lowest-ceiling": {
    title: "Autonomy is scoped and the lowest ceiling wins",
    path: "/docs/01-understand/03-first-principles-trust-evidence-and-authority#autonomy-is-scoped-and-the-lowest-ceiling-wins",
    lastReviewed: "2026-09-04",
  },
  "authority.permission": {
    title: "Permission is not authority",
    path: "/docs/02-design/07-governance-policy-and-risk-proportional-approval#permission-is-not-authority",
    lastReviewed: "2026-09-04",
  },
  "autonomy.per-action": {
    title: "Autonomy per action class",
    path: "/docs/02-design/07-governance-policy-and-risk-proportional-approval#autonomy-per-action-class",
    lastReviewed: "2026-09-04",
  },
  "trust.evidence-record": {
    title: "The evidence record",
    path: "/docs/04-prove/27-quality-and-evidence-architecture#the-evidence-record",
    lastReviewed: "2026-09-04",
  },
  "trust.independent-verification": {
    title: "Validation must be independent",
    path: "/docs/04-prove/27-quality-and-evidence-architecture#validation-must-be-independent",
    lastReviewed: "2026-09-04",
  },
  "trust.verification-contract": {
    title: "The verification contract",
    path: "/docs/04-prove/27-quality-and-evidence-architecture#the-verification-contract",
    lastReviewed: "2026-09-04",
  },
  "records.traceability": {
    title: "The traceability chain",
    path: "/docs/02-design/05-authoritative-records#the-traceability-chain",
    lastReviewed: "2026-09-04",
  },
  "capability.agent-definition": {
    title: "The Agent Definition is a contract, not a prompt",
    path: "/docs/03-build/11-the-agent-factory#the-agent-definition-is-a-contract-not-a-prompt",
    lastReviewed: "2026-09-04",
  },
  "capability.factory-boundary": {
    title: "Two factories, one boundary",
    path: "/docs/03-build/11-the-agent-factory#two-factories-one-boundary",
    lastReviewed: "2026-09-04",
  },
  "context.retrieval-contract": {
    title: "The retrieval contract",
    path: "/docs/03-build/20-context-engineering#the-retrieval-contract",
    lastReviewed: "2026-09-04",
  },
  "field.forward-deployed-loop": {
    title: "Forward-deployed engineering and its failure mode",
    path: "/docs/05-operate/38-enterprise-adoption-and-the-infrastructure-landscape#forward-deployed-engineering-and-its-failure-mode",
    lastReviewed: "2026-09-04",
  },
} as const;

export type GuideTopic = keyof typeof GUIDE_LINKS;

export function guideHref(topic: GuideTopic): string {
  return `${GUIDE_BASE_URL}${GUIDE_LINKS[topic].path}`;
}
