import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatTime(raw: string | number | Date): string {
  let date: Date
  if (typeof raw === "string") {
    date = new Date(raw.includes("T") ? raw : raw.replace(" ", "T"))
  } else if (typeof raw === "number") {
    date = new Date(raw < 1e12 ? raw * 1000 : raw)
  } else {
    date = new Date(raw)
  }

  if (isNaN(date.getTime())) return ""

  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffSec = Math.floor(diffMs / 1000)
  const diffMin = Math.floor(diffSec / 60)
  const diffHour = Math.floor(diffMin / 60)
  const diffDay = Math.floor(diffHour / 24)
  const sameYear = date.getFullYear() === now.getFullYear()

  if (diffSec < 10) return "刚刚"
  if (diffMin < 1) return `${diffSec} 秒前`
  if (diffMin < 60) return `${diffMin} 分钟前`
  if (diffHour < 24) return `${diffHour} 小时前`
  if (diffDay < 7) return `${diffDay} 天前`

  if (sameYear) {
    return date.toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    })
  }

  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}
