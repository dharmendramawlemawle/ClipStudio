import React from 'react';
import { Layers, Clock, AlertTriangle, CheckCircle, RotateCw } from 'lucide-react';
import { ProcessingJob } from '../types';

interface JobsTableProps {
  jobs: ProcessingJob[];
  loading: boolean;
  onRefresh: () => void;
  onSelectJob: (job: ProcessingJob) => void;
}

export const JobsTable: React.FC<JobsTableProps> = ({
  jobs,
  loading,
  onRefresh,
  onSelectJob,
}) => {
  return (
    <div className="bg-studio-900 border border-studio-800 rounded-xl overflow-hidden shadow-xl">
      <div className="p-5 border-b border-studio-800 flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <Layers className="w-5 h-5 text-brand-500" />
          <h3 className="font-bold text-white text-base">Persistent Job History (SQLite)</h3>
          <span className="text-xs bg-studio-800 text-studio-300 px-2 py-0.5 rounded-full font-mono">
            {jobs.length} records
          </span>
        </div>
        <button
          onClick={onRefresh}
          disabled={loading}
          className="flex items-center space-x-1.5 text-xs text-studio-400 hover:text-white transition px-2.5 py-1 rounded bg-studio-800 hover:bg-studio-700"
        >
          <RotateCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span>Refresh List</span>
        </button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="bg-studio-950/70 border-b border-studio-800 text-studio-400 uppercase tracking-wider font-semibold">
            <tr>
              <th className="py-3 px-4">Job ID</th>
              <th className="py-3 px-4">Type</th>
              <th className="py-3 px-4">Status</th>
              <th className="py-3 px-4">Progress</th>
              <th className="py-3 px-4">Current Step</th>
              <th className="py-3 px-4">Created</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-studio-800/60 font-medium">
            {jobs.length === 0 ? (
              <tr>
                <td colSpan={6} className="py-8 text-center text-studio-400">
                  No jobs logged in database yet. Launch a test job above!
                </td>
              </tr>
            ) : (
              jobs.map((job) => {
                const isRunning = job.status === 'running' || job.status === 'queued';
                const isCompleted = job.status === 'completed';
                const isFailed = job.status === 'failed';

                return (
                  <tr
                    key={job.id}
                    onClick={() => onSelectJob(job)}
                    className="hover:bg-studio-850/50 cursor-pointer transition"
                  >
                    <td className="py-3 px-4 font-mono text-studio-300">
                      {job.id.substring(0, 8)}...
                    </td>
                    <td className="py-3 px-4 text-white font-semibold">{job.job_type}</td>
                    <td className="py-3 px-4">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold uppercase ${
                          isCompleted
                            ? 'bg-brand-500/10 text-brand-500 border border-brand-500/20'
                            : isRunning
                            ? 'bg-yellow-500/10 text-yellow-400 border border-yellow-500/20 animate-pulse'
                            : isFailed
                            ? 'bg-red-500/10 text-red-400 border border-red-500/20'
                            : 'bg-studio-800 text-studio-400'
                        }`}
                      >
                        {isCompleted && <CheckCircle className="w-3 h-3 mr-1" />}
                        {isFailed && <AlertTriangle className="w-3 h-3 mr-1" />}
                        {isRunning && <Clock className="w-3 h-3 mr-1" />}
                        {job.status}
                      </span>
                    </td>
                    <td className="py-3 px-4">
                      <div className="w-24 bg-studio-800 h-2 rounded-full overflow-hidden">
                        <div
                          className={`h-full ${isCompleted ? 'bg-brand-500' : isFailed ? 'bg-red-500' : 'bg-brand-500'}`}
                          style={{ width: `${job.progress_percent}%` }}
                        />
                      </div>
                      <span className="text-[10px] text-studio-400 mt-0.5 block font-mono">
                        {job.progress_percent.toFixed(0)}%
                      </span>
                    </td>
                    <td className="py-3 px-4 text-studio-300 truncate max-w-xs" title={job.current_step}>
                      {job.current_step}
                    </td>
                    <td className="py-3 px-4 text-studio-400 font-mono">
                      {new Date(job.created_at).toLocaleTimeString()}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
