"use client"

import { SectionScore } from "@/lib/api"
import { cn } from "@/lib/utils"

interface ScoreCardProps {
  section: SectionScore
}

export function ScoreCard({ section }: ScoreCardProps) {
  const getScoreColor = (score: number) => {
    if (score >= 80) return "bg-green-500"
    if (score >= 60) return "bg-green-400"
    if (score >= 40) return "bg-yellow-400"
    if (score >= 20) return "bg-orange-400"
    return "bg-red-500"
  }

  return (
    <div className="bg-white rounded-lg shadow-md p-6 border border-gray-200">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-gray-800">{section.name}</h3>
        <div className="flex items-center gap-2">
          <div className={cn("w-3 h-3 rounded-full", getScoreColor(section.score))} />
          <span className="text-2xl font-bold text-gray-900">{section.score}</span>
          <span className="text-sm text-gray-500">/100</span>
        </div>
      </div>
      
      {section.signals.length > 0 && (
        <div className="mb-4">
          <h4 className="text-sm font-medium text-gray-700 mb-2">Key Signals:</h4>
          <ul className="list-disc list-inside space-y-1 text-sm text-gray-600">
            {section.signals.slice(0, 3).map((signal, idx) => (
              <li key={idx}>{signal}</li>
            ))}
          </ul>
        </div>
      )}
      
      <p className="text-sm text-gray-600 line-clamp-3">{section.reasoning}</p>
    </div>
  )
}

