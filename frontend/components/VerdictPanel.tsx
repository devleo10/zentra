"use client"

import { VerdictResponse } from "@/lib/api"
import { cn } from "@/lib/utils"

interface VerdictPanelProps {
  verdict: VerdictResponse
}

export function VerdictPanel({ verdict }: VerdictPanelProps) {
  const getBiasColor = (bias: string | null | undefined) => {
    const biasLower = (bias ?? "").toLowerCase()
    if (biasLower.includes("bull")) return "bg-green-500"
    if (biasLower.includes("bear")) return "bg-red-500"
    if (biasLower.includes("neutral")) return "bg-yellow-400"
    return "bg-gray-400"
  }

  return (
    <div className="bg-gradient-to-r from-blue-50 to-indigo-50 rounded-lg shadow-lg p-6 border-2 border-blue-200">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-2xl font-bold text-gray-800">Final Verdict</h2>
        <div className={cn("px-4 py-2 rounded-full text-white font-semibold", getBiasColor(verdict.bias))}>
          {verdict.bias}
        </div>
      </div>
      
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div>
          <p className="text-sm text-gray-600">Final Score</p>
          <p className="text-3xl font-bold text-gray-900">{verdict.final_score}/100</p>
        </div>
        <div>
          <p className="text-sm text-gray-600">Confidence</p>
          <p className="text-xl font-semibold text-gray-800">{verdict.confidence}</p>
        </div>
      </div>
      
      <div className="mb-4">
        <p className="text-sm font-medium text-gray-700 mb-2">Recommended Action:</p>
        <p className="text-lg text-gray-800">{verdict.action}</p>
      </div>
      
      <div className="bg-white rounded p-4">
        <p className="text-sm text-gray-700">{verdict.summary}</p>
      </div>
    </div>
  )
}


