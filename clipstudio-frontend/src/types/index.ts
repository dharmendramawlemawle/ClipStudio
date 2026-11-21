export interface HealthResponse {
  status: 'ok' | 'degraded' | 'error';
  app_name: string;
  version: string;
  timestamp: string;
  database: string;
  active_jobs: number;
  hardware: {
    platform?: string;
    cpu_threads_configured?: number;
    max_concurrent_heavy_jobs?: number;
    [key: string]: any;
  };
}

export interface ProcessingJob {
  id: string;
  entity_type: string;
  entity_id: string | null;
  job_type: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  progress_percent: number;
  current_step: string;
  result_data: string | null;
  error_message: string | null;
  retry_count: number;
  max_retries: number;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface JobProgressEvent {
  event_type: 'job_progress';
  job_id: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  progress_percent: number;
  current_step: string;
  message: string;
  timestamp: string;
}

export interface Workspace {
  id: string;
  name: string;
  description: string | null;
  local_storage_path: string;
  created_at: string;
  updated_at: string;
}
