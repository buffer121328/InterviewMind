import * as React from "react"
import { cn } from "@/lib/utils"

export interface CheckboxProps extends React.InputHTMLAttributes<HTMLInputElement> {
    onCheckedChange?: (checked: boolean) => void
}

const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
    ({ className, onCheckedChange, checked, ...props }, ref) => {
        return (
            <input
                type="checkbox"
                ref={ref}
                checked={checked}
                onChange={(e) => onCheckedChange?.(e.target.checked)}
                className={cn(
                    "h-4 w-4 shrink-0 rounded border border-gray-300 bg-white text-orange-600",
                    "focus:ring-2 focus:ring-orange-500 focus:ring-offset-0",
                    "disabled:cursor-not-allowed disabled:opacity-50",
                    "accent-orange-600",
                    className
                )}
                {...props}
            />
        )
    }
)
Checkbox.displayName = "Checkbox"

export { Checkbox }
