/**
 * TimeframeAnalysis Component
 * 
 * Displays Bitcoin macro analysis across different timeframes
 * with comparison and trend visualization
 */
"use client";

import React, { useState, useEffect } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { TrendingUp, TrendingDown, Minus, Clock, BarChart3 } from 'lucide-react';

interface AnalysisResult {
  timestamp: string;
  final_score: number;
  bias: string;
  action: string;
  confidence_pct: number;
  confidence_label: string;
  section_scores: Record<string, number>;
  reasoning?: string;
}

interface ComparisonResult {
  timeframes_analyzed: string[];
  results: Record<string, AnalysisResult>;
  summary: {
    score_analysis: {
      scores: Record<string, number>;
      trend: string;
      volatility: number;
      range: string;
    };
    bias_analysis: {
      biases: Record<string, string>;
      consistent: boolean;
      unique_biases: string[];
    };
    confidence_analysis: {
      scores: Record<string, number>;
      average: number;
      stability: string;
    };
    recommendation: string;
  };
  generated_at: string;
}

const TIMEFRAMES = [
  { key: 'current', label: 'Current', description: 'Real-time snapshot' },
  { key: 'week', label: '7 Days', description: '7-day trends' },
  { key: 'month', label: 'Month-to-Date', description: 'MTD analysis' },
  { key: 'year', label: '1 Year', description: 'Annual perspective' }
];

const getBiasColor = (bias: string): string => {
  const lowerBias = bias.toLowerCase();
  if (lowerBias.includes('strong bull')) return 'bg-green-600';
  if (lowerBias.includes('bullish')) return 'bg-green-500';
  if (lowerBias.includes('neutral')) return 'bg-gray-500';
  if (lowerBias.includes('bearish')) return 'bg-red-500';
  if (lowerBias.includes('high risk')) return 'bg-red-600';
  return 'bg-gray-400';
};

const getScoreColor = (score: number): string => {
  if (score >= 80) return 'text-green-600';
  if (score >= 65) return 'text-green-500';
  if (score >= 40) return 'text-yellow-500';
  if (score >= 20) return 'text-red-500';
  return 'text-red-600';
};

const getTrendIcon = (trend: string) => {
  if (trend === 'improving') return <TrendingUp className="h-4 w-4 text-green-500" />;
  if (trend === 'deteriorating') return <TrendingDown className="h-4 w-4 text-red-500" />;
  return <Minus className="h-4 w-4 text-gray-500" />;
};

export default function TimeframeAnalysis() {
  const [analysisResults, setAnalysisResults] = useState<Record<string, AnalysisResult | null>>({});
  const [comparison, setComparison] = useState<ComparisonResult | null>(null);
  const [loading, setLoading] = useState<Record<string, boolean>>({});
  const [activeTab, setActiveTab] = useState('individual');
  const [error, setError] = useState<string | null>(null);

  const runAnalysis = async (timeframe: string) => {
    setLoading(prev => ({ ...prev, [timeframe]: true }));
    setError(null);

    try {
      const response = await fetch(`/api/v2/analyze/${timeframe}`);
      if (!response.ok) {
        throw new Error(`Analysis failed: ${response.statusText}`);
      }
      
      const result = await response.json();
      setAnalysisResults(prev => ({ ...prev, [timeframe]: result }));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Analysis failed');
      console.error('Analysis error:', err);
    } finally {
      setLoading(prev => ({ ...prev, [timeframe]: false }));
    }
  };

  const runComparison = async () => {
    setLoading(prev => ({ ...prev, comparison: true }));
    setError(null);

    try {
      const response = await fetch('/api/v2/analyze/compare?timeframes=current,week,month,year');
      if (!response.ok) {
        throw new Error(`Comparison failed: ${response.statusText}`);
      }
      
      const result = await response.json();
      setComparison(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Comparison failed');
      console.error('Comparison error:', err);
    } finally {
      setLoading(prev => ({ ...prev, comparison: false }));
    }
  };

  const runAllAnalyses = () => {
    TIMEFRAMES.forEach(tf => runAnalysis(tf.key));
  };

  const renderAnalysisCard = (timeframe: string, result: AnalysisResult | null) => {
    const tfConfig = TIMEFRAMES.find(tf => tf.key === timeframe);
    const isLoading = loading[timeframe];

    return (
      <Card key={timeframe} className="w-full">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <div>
            <CardTitle className="text-base font-medium">{tfConfig?.label}</CardTitle>
            <CardDescription>{tfConfig?.description}</CardDescription>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => runAnalysis(timeframe)}
            disabled={isLoading}
            className="shrink-0"
          >
            {isLoading ? (
              <>
                <Clock className="h-4 w-4 mr-2 animate-spin" />
                Running...
              </>
            ) : (
              'Analyze'
            )}
          </Button>
        </CardHeader>
        
        <CardContent className="pt-4">
          {result ? (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="space-y-1">
                  <div className={`text-2xl font-bold ${getScoreColor(result.final_score)}`}>
                    {result.final_score}/100
                  </div>
                  <Badge className={getBiasColor(result.bias)}>
                    {result.bias}
                  </Badge>
                </div>
                <div className="text-right text-sm text-muted-foreground">
                  <div>Confidence: {result.confidence_pct}%</div>
                  <div>{result.confidence_label}</div>
                </div>
              </div>

              <div className="space-y-2">
                <div className="text-sm font-medium">Action:</div>
                <div className="text-sm text-muted-foreground">{result.action}</div>
              </div>

              <div className="grid grid-cols-2 gap-2 text-xs">
                {Object.entries(result.section_scores).map(([section, score]) => (
                  <div key={section} className="flex justify-between p-2 bg-muted rounded">
                    <span className="truncate">{section.replace('_', ' ')}</span>
                    <span className={getScoreColor(score)}>{score}</span>
                  </div>
                ))}
              </div>

              <div className="text-xs text-muted-foreground">
                Updated: {new Date(result.timestamp).toLocaleString()}
              </div>
            </div>
          ) : (
            <div className="text-center text-muted-foreground py-8">
              Click "Analyze" to run {tfConfig?.label.toLowerCase()} analysis
            </div>
          )}
        </CardContent>
      </Card>
    );
  };

  return (
    <div className="space-y-6 text-white">
      <div className="flex justify-between items-center">
        <div>
          <h2 className="text-2xl font-bold text-white">Timeframe Analysis</h2>
          <p className="text-gray-400">
            Bitcoin macro analysis across different time horizons
          </p>
        </div>
        <div className="flex gap-2">
          <Button onClick={runAllAnalyses} variant="outline">
            <BarChart3 className="h-4 w-4 mr-2" />
            Run All
          </Button>
          <Button onClick={runComparison} disabled={loading.comparison}>
            {loading.comparison ? (
              <>
                <Clock className="h-4 w-4 mr-2 animate-spin" />
                Comparing...
              </>
            ) : (
              'Compare All'
            )}
          </Button>
        </div>
      </div>

      {error && (
        <Card className="border-red-600 bg-red-900/20">
          <CardContent className="p-4">
            <div className="text-red-300">Error: {error}</div>
          </CardContent>
        </Card>
      )}

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="individual">Individual Analysis</TabsTrigger>
          <TabsTrigger value="comparison">Timeframe Comparison</TabsTrigger>
        </TabsList>

        <TabsContent value="individual" className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {TIMEFRAMES.map(tf => renderAnalysisCard(tf.key, analysisResults[tf.key]))}
          </div>
        </TabsContent>

        <TabsContent value="comparison" className="space-y-4">
          {comparison ? (
            <div className="space-y-6">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <BarChart3 className="h-5 w-5" />
                    Cross-Timeframe Comparison
                  </CardTitle>
                  <CardDescription>
                    Generated: {new Date(comparison.generated_at).toLocaleString()}
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                  {/* Score Analysis */}
                  <div>
                    <h4 className="font-medium mb-3 flex items-center gap-2">
                      Score Trend Analysis {getTrendIcon(comparison.summary.score_analysis.trend)}
                    </h4>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                      {Object.entries(comparison.summary.score_analysis.scores).map(([tf, score]) => (
                        <div key={tf} className="text-center p-3 bg-muted rounded">
                          <div className="text-sm text-muted-foreground capitalize">{tf}</div>
                          <div className={`text-xl font-bold ${getScoreColor(score)}`}>{score}</div>
                        </div>
                      ))}
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
                      <div>
                        <span className="text-muted-foreground">Trend: </span>
                        <span className="capitalize">{comparison.summary.score_analysis.trend}</span>
                      </div>
                      <div>
                        <span className="text-muted-foreground">Volatility: </span>
                        <span>{comparison.summary.score_analysis.volatility}</span>
                      </div>
                      <div>
                        <span className="text-muted-foreground">Range: </span>
                        <span>{comparison.summary.score_analysis.range}</span>
                      </div>
                    </div>
                  </div>

                  {/* Bias Analysis */}
                  <div>
                    <h4 className="font-medium mb-3">Bias Consistency</h4>
                    <div className="flex flex-wrap gap-2 mb-3">
                      {Object.entries(comparison.summary.bias_analysis.biases).map(([tf, bias]) => (
                        <Badge key={tf} className={getBiasColor(bias)}>
                          {tf}: {bias}
                        </Badge>
                      ))}
                    </div>
                    <div className="text-sm text-muted-foreground">
                      {comparison.summary.bias_analysis.consistent ? (
                        <span className="text-green-600">✓ Consistent bias across timeframes</span>
                      ) : (
                        <span className="text-yellow-600">⚠ Mixed biases detected</span>
                      )}
                    </div>
                  </div>

                  {/* Confidence Analysis */}
                  <div>
                    <h4 className="font-medium mb-3">Confidence Assessment</h4>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
                      <div>
                        <span className="text-muted-foreground">Average: </span>
                        <span>{comparison.summary.confidence_analysis.average}%</span>
                      </div>
                      <div>
                        <span className="text-muted-foreground">Stability: </span>
                        <span className="capitalize">{comparison.summary.confidence_analysis.stability}</span>
                      </div>
                    </div>
                  </div>

                  {/* Recommendation */}
                  <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
                    <h4 className="font-medium text-blue-900 mb-2">Recommendation</h4>
                    <p className="text-blue-800 text-sm">{comparison.summary.recommendation}</p>
                  </div>
                </CardContent>
              </Card>

              {/* Individual Results Grid */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {comparison.timeframes_analyzed.map(tf => 
                  renderAnalysisCard(tf, comparison.results[tf])
                )}
              </div>
            </div>
          ) : (
            <Card>
              <CardContent className="p-8 text-center">
                <div className="text-muted-foreground mb-4">
                  No comparison data available
                </div>
                <Button onClick={runComparison} disabled={loading.comparison}>
                  Run Timeframe Comparison
                </Button>
              </CardContent>
            </Card>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}