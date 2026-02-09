"use client"

interface ScoreGaugeProps {
  score: number
  size?: number
}

export function ScoreGauge({ score, size = 200 }: ScoreGaugeProps) {
  const getColor = (score: number) => {
    if (score >= 80) return "#10b981" // green
    if (score >= 60) return "#34d399" // light green
    if (score >= 40) return "#fbbf24" // yellow
    if (score >= 20) return "#fb923c" // orange
    return "#ef4444" // red
  }

  const getBias = (score: number) => {
    if (score >= 80) return "Strong Bull"
    if (score >= 60) return "Bullish"
    if (score >= 40) return "Neutral"
    if (score >= 20) return "Bearish"
    return "High Risk"
  }

  const circumference = 2 * Math.PI * 90 // radius = 90
  const offset = circumference - (score / 100) * circumference
  const color = getColor(score)

  return (
    <div className="flex flex-col items-center">
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="transform -rotate-90">
          {/* Background circle */}
          <circle
            cx={size / 2}
            cy={size / 2}
            r="90"
            stroke="#e5e7eb"
            strokeWidth="12"
            fill="none"
          />
          {/* Progress circle */}
          <circle
            cx={size / 2}
            cy={size / 2}
            r="90"
            stroke={color}
            strokeWidth="12"
            fill="none"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            strokeLinecap="round"
            className="transition-all duration-500"
          />
        </svg>
        {/* Score text */}
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="text-center">
            <div className="text-5xl font-bold" style={{ color }}>
              {score}
            </div>
            <div className="text-sm text-gray-500">/100</div>
          </div>
        </div>
      </div>
      <p className="mt-4 text-xl font-semibold" style={{ color }}>
        {getBias(score)}
      </p>
    </div>
  )
}

