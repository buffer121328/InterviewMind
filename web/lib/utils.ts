import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

// 合并CSS类名的工具函数
/** Encapsulates cn; returns typed data or state and keeps side effects within the owning module boundary. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
