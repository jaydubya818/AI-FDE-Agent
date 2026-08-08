import { EngagementCockpit } from "@/components/engagement-cockpit";

export default async function EngagementPage({
  params,
}: {
  params: Promise<{ engagementId: string }>;
}) {
  const { engagementId } = await params;
  return <EngagementCockpit engagementId={engagementId} />;
}
