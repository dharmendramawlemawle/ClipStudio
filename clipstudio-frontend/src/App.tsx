import { useState, useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Header } from './components/Header';
import { Sidebar } from './components/Sidebar';
import { JobTester } from './components/JobTester';
import { JobsTable } from './components/JobsTable';
import { fetchHealth, fetchJobs } from './api/client';
import { useWebSocket } from './hooks/useWebSocket';
import { ProcessingJob, JobProgressEvent } from './types';
import { HardDrive, Cpu, FolderCheck, CheckCircle2 } from 'lucide-react';

export function App() {
  const queryClient = useQueryClient();
  const [currentTab, setCurrentTab] = useState('dashboard');
  const [activeJob, setActiveJob] = useState<ProcessingJob | null>(null);

  // 1. Fetch Backend Health Status (poll every 15s)
  const {
    data: health,
    isLoading: healthLoading,
    refetch: refetchHealth,
  } = useQuery({
    queryKey: ['health'],
    queryFn: fetchHealth,
    refetchInterval: 15000,
  });

  // 2. Fetch Historical Jobs via REST API
  const {
    data: jobs = [],
    isLoading: jobsLoading,
    refetch: refetchJobs,
  } = useQuery({
    queryKey: ['jobs'],
    queryFn: () => fetchJobs(30),
  });

  // 3. Auto-restore active or most recent job on initial load or refresh
  useEffect(() => {
    if (jobs.length > 0 && !activeJob) {
      // Find currently running job or fallback to latest job
      const running = jobs.find((j) => j.status === 'running' || j.status === 'queued');
      setActiveJob(running || jobs[0]);
    }
  }, [jobs, activeJob]);

  // 4. WebSocket progress event handler
  const handleJobProgress = (event: JobProgressEvent) => {
    // Update active job if matching or newly created
    setActiveJob((prev) => {
      if (!prev || prev.id === event.job_id) {
        return {
          id: event.job_id,
          entity_type: prev?.entity_type || 'test',
          entity_id: prev?.entity_id || null,
          job_type: prev?.job_type || 'test_job',
          status: event.status,
          progress_percent: event.progress_percent,
          current_step: event.current_step,
          result_data: prev?.result_data || null,
          error_message: event.status === 'failed' ? event.message : null,
          retry_count: prev?.retry_count || 0,
          max_retries: prev?.max_retries || 3,
          started_at: prev?.started_at || new Date().toISOString(),
          completed_at: event.status === 'completed' || event.status === 'failed' ? new Date().toISOString() : null,
          created_at: prev?.created_at || new Date().toISOString(),
          updated_at: event.timestamp,
        };
      }
      return prev;
    });

    // Invalidate & refresh query cache so jobs table is synchronized
    queryClient.invalidateQueries({ queryKey: ['jobs'] });
  };

  // 5. Connect WebSocket
  const { status: wsStatus, reconnect: reconnectWS } = useWebSocket(handleJobProgress);

  return (
    <div className="min-h-screen flex flex-col bg-studio-950 text-studio-100">
      {/* Top Header */}
      <Header
        health={health ?? null}
        healthLoading={healthLoading}
        wsStatus={wsStatus}
        onRefreshHealth={() => refetchHealth()}
        onReconnectWS={reconnectWS}
      />

      <div className="flex-1 flex overflow-hidden">
        {/* Navigation Sidebar */}
        <Sidebar
          currentTab={currentTab}
          onSelectTab={setCurrentTab}
          health={health ?? null}
        />

        {/* Main Workspace Body */}
        <main className="flex-1 overflow-y-auto p-8 space-y-8 max-w-7xl mx-auto w-full">
          {/* Welcome Banner */}
          <div className="flex items-center justify-between pb-4 border-b border-studio-800">
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-white">
                ClipStudio Workspace
              </h1>
              <p className="text-sm text-studio-400 mt-1">
                Phase 1 Scaffolding — Verified Async Core, SQLite WAL Engine & WebSocket Telemetry
              </p>
            </div>
            <div className="flex items-center space-x-2 text-xs bg-brand-500/10 border border-brand-500/20 text-brand-500 px-3 py-1.5 rounded-lg">
              <CheckCircle2 className="w-4 h-4" />
              <span>Independent Architecture Active</span>
            </div>
          </div>

          {/* Foundation Health & Metrics Row */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
            {/* Storage Metric */}
            <div className="bg-studio-900 border border-studio-800 rounded-xl p-5 shadow-lg flex items-center space-x-4">
              <div className="w-12 h-12 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center shrink-0">
                <HardDrive className="w-6 h-6 text-blue-400" />
              </div>
              <div>
                <p className="text-xs text-studio-400 uppercase font-semibold">Database Engine</p>
                <p className="text-base font-bold text-white mt-0.5">SQLite 3 (WAL Mode)</p>
                <p className="text-xs text-blue-400 font-mono mt-0.5">clipstudio.db • Migrated</p>
              </div>
            </div>

            {/* Hardware Profile Metric */}
            <div className="bg-studio-900 border border-studio-800 rounded-xl p-5 shadow-lg flex items-center space-x-4">
              <div className="w-12 h-12 rounded-lg bg-brand-500/10 border border-brand-500/20 flex items-center justify-center shrink-0">
                <Cpu className="w-6 h-6 text-brand-500" />
              </div>
              <div>
                <p className="text-xs text-studio-400 uppercase font-semibold">Hardware Allocation</p>
                <p className="text-base font-bold text-white mt-0.5">Intel i5-1135G7 (4 Threads)</p>
                <p className="text-xs text-brand-500 font-mono mt-0.5">1 Heavy Job Limit Active</p>
              </div>
            </div>

            {/* Storage Directory Metric */}
            <div className="bg-studio-900 border border-studio-800 rounded-xl p-5 shadow-lg flex items-center space-x-4">
              <div className="w-12 h-12 rounded-lg bg-purple-500/10 border border-purple-500/20 flex items-center justify-center shrink-0">
                <FolderCheck className="w-6 h-6 text-purple-400" />
              </div>
              <div>
                <p className="text-xs text-studio-400 uppercase font-semibold">Local Media Directory</p>
                <p className="text-base font-bold text-white mt-0.5">D:/dharmendra/clipstudio/data</p>
                <p className="text-xs text-purple-400 font-mono mt-0.5">Ready for Phase 2 Ingestion</p>
              </div>
            </div>
          </div>

          {/* Test Job Interactive Runner */}
          <JobTester
            activeJob={activeJob}
            onJobCreated={(newJob) => {
              setActiveJob(newJob);
              refetchJobs();
            }}
          />

          {/* Historical Jobs Table */}
          <JobsTable
            jobs={jobs}
            loading={jobsLoading}
            onRefresh={() => refetchJobs()}
            onSelectJob={(job) => setActiveJob(job)}
          />
        </main>
      </div>
    </div>
  );
}
