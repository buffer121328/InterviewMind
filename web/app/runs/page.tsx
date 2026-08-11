import { RunCenter } from '@/components/RunCenter';

/** Renders the agent run stats page UI and coordinates its typed props, local state, and approved backend interactions. */
export default function AgentRunStatsPage() {
    return (
        <main className="h-[100dvh] min-h-0 overflow-hidden bg-[#f7faf9]">
            <RunCenter />
        </main>
    );
}
