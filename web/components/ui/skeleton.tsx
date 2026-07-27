import { cn } from "@/lib/utils"

/** Wraps the skeleton primitive while forwarding its typed props/ref and preserving the underlying accessibility semantics. */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      className={cn("bg-accent animate-pulse rounded-md", className)}
      {...props}
    />
  )
}

export { Skeleton }
