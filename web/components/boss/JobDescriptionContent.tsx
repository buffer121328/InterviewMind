import { getJobDescriptionBlocks } from '@/lib/bossJobDescriptionPresentation';

interface JobDescriptionContentProps {
    description: string;
    className?: string;
}

/** Displays captured JD paragraphs and bullet-like requirements without mutating their source order. */
export function JobDescriptionContent({ description, className = '' }: JobDescriptionContentProps) {
    const blocks = getJobDescriptionBlocks(description);
    return (
        <div className={`space-y-2 ${className}`.trim()}>
            {blocks.map((block, index) => block.kind === 'list' ? (
                <ul key={`list-${index}`} className="list-disc space-y-1 pl-5 marker:text-teal-500">
                    {block.items.map((item, itemIndex) => <li key={`${index}-${itemIndex}`}>{item}</li>)}
                </ul>
            ) : (
                <p key={`paragraph-${index}`} className="whitespace-pre-wrap">{block.text}</p>
            ))}
        </div>
    );
}
