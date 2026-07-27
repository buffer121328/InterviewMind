import { Headphones } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useInterviewStore } from "@/store/useInterviewStore";

/** Renders the voice toggle button UI and coordinates its typed props, local state, and approved backend interactions. */
export function VoiceToggleButton() {
    const setVoiceMode = useInterviewStore((state) => state.setVoiceMode);

    return (
        <Button
            variant="ghost"
            size="sm"
            onClick={() => setVoiceMode(true)}
            className="gap-2 text-orange-600 hover:text-orange-700 hover:bg-orange-50"
        >
            <Headphones className="w-4 h-4" />
            语音模式
        </Button>
    );
}
