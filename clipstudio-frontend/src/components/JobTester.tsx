import React, { useState } from 'react';
import { Play, CheckCircle2, AlertCircle, Loader2, XCircle } from 'lucide-react';
import { triggerTestJob, cancelJob } from '../api/client';
import { ProcessingJob } from '../types';

interface JobTesterProps {
  activeJob: ProcessingJob | null;
  onJobCreated: (job: ProcessingJob) => void;
}

export const JobTester: React.FC<JobTesterProps> = ({ activeJob, onJobCreated }) => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleStartTest = async () => {
    try {
      setLoading(true);
      setError(null);
      const newJob = await triggerTestJob({
        test_type: 'phase1_verification',
        timestamp: new Date().toISOString(),
      });
      onJobCreated(newJob);
    } catch (err: any) {
      setError(err.message || 'Failed to trigger test job');
    } finally {
      setLoading(false);
    }
  };

  const handleCancel = async () => {
    if (!activeJob) return;
    try {
      await cancelJob(activeJob.id);
    } catch (err: any) {
      setError(err.message || 'Failed to cancel job');
    }
  };

  const isRunning = activeJob?.status === 'running' || activeJob?.status === 'queued';
  const isCompleted = activeJob?.status === 'completed';
  const isFailed = activeJob?.status === 'failed';
  const isCancelled = activeJob?.status === 'cancelled';

  return (
    <div className="bg-studio-900 border border-studio-800 rounded-xl p-6 shadow-xl relative overflow-hidden">
      {/* Top Banner */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center space-x-2">
            <h2 className="text-lg font-bold text-white tracking-tight">Phase 1 Durable Job Verification</h2>
            <span className="text-xs bg-brand-500/10 text-brand-500 font-semibold px-2 py-0.5 rounded border border-brand-500/20">
              In-Process Async Worker
            </span>
          </div>
          <p className="text-sm text-studio-400 mt-1">
            Tests the complete durable lifecycle: <code className="text-studio-200">queued → running → WebSocket progress → SQLite persistence → completed</code>.
          </p>
        </div>

        {/* Action Button */}
        <div>
          {!isRunning ? (
            <button
              onClick={handleStartTest}
              disabled={loading}
              className="flex items-center space-x-2 bg-brand-500 hover:bg-brand-600 active:scale-95 text-black font-semibold px-5 py-2.5 rounded-lg transition shadow-lg shadow-brand-500/20 disabled:opacity-50"
            >
              {loading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Submitting...</span>
                </>
              ) : (
                <>
                  <Play className="w-4 h-4 fill-black" />
                  <span>Execute Test Job</span>
                </>
              )}
            </button>
          ) : (
            <button
              onClick={handleCancel}
              className="flex items-center space-x-2 bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/30 font-semibold px-4 py-2.5 rounded-lg transition"
            >
              <XCircle className="w-4 h-4" />
              <span>Abort Job</span>
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm flex items-center space-x-2">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Active Job Progress Display */}
      {activeJob && (
        <div className="bg-studio-950 border border-studio-800 rounded-lg p-5 space-y-4">
          <div className="flex items-center justify-between text-xs text-studio-400">
            <div>
              <span className="font-semibold text-studio-200">Job ID:</span>{' '}
              <span className="font-mono text-studio-400">{activeJob.id}</span>
            </div>
            <div className="flex items-center space-x-2">
              <span className="font-semibold text-studio-200">Status:</span>
              <span
                className={`font-semibold uppercase tracking-wider px-2 py-0.5 rounded text-[11px] ${
                  isCompleted
                    ? 'bg-brand-500/20 text-brand-500 border border-brand-500/30'
                    : isRunning
                    ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30 animate-pulse'
                    : isFailed
                    ? 'bg-red-500/20 text-red-400 border border-red-500/30'
                    : 'bg-studio-800 text-studio-400'
                }`}
              >
                {activeJob.status}
              </span>
            </div>
          </div>

          {/* Progress Bar */}
          <div className="space-y-1.5">
            <div className="flex justify-between text-xs">
              <span className="text-studio-300 font-medium">{activeJob.current_step}</span>
              <span className="font-mono font-bold text-white">{activeJob.progress_percent.toFixed(0)}%</span>
            </div>
            <div className="h-3 w-full bg-studio-850 rounded-full overflow-hidden border border-studio-800">
              <div
                className={`h-full transition-all duration-300 ease-out rounded-full ${
                  isCompleted
                    ? 'bg-brand-500'
                    : isFailed
                    ? 'bg-red-500'
                    : isCancelled
                    ? 'bg-zinc-500'
                    : 'bg-gradient-to-r from-brand-600 to-brand-500'
                }`}
                style={{ width: `${Math.max(activeJob.progress_percent, 2)}%` }}
              />
            </div>
          </div>

          {/* Execution Telemetry Details */}
          <div className="pt-2 border-t border-studio-850 flex items-center justify-between text-xs text-studio-400">
            <div>
              <span>Created: </span>
              <span className="text-studio-300">{new Date(activeJob.created_at).toLocaleTimeString()}</span>
              {activeJob.completed_at && (
                <>
                  <span className="mx-2">•</span>
                  <span>Finished: </span>
                  <span className="text-studio-300">{new Date(activeJob.completed_at).toLocaleTimeString()}</span>
                </>
              )}
            </div>

            {isCompleted && (
              <div className="flex items-center text-brand-500 font-medium">
                <CheckCircle2 className="w-4 h-4 mr-1" />
                <span>Verified in SQLite & WebSocket</span>
              </div>
            )}
          </div>
        </div>
      )}

      {!activeJob && (
        <div className="border border-dashed border-studio-800 rounded-lg p-8 text-center text-studio-400">
          <p className="text-sm">No test job active. Click <strong className="text-studio-200">"Execute Test Job"</strong> to run a live multi-stage verification.</p>
        </div>
      )}
    </div>
  );
};
