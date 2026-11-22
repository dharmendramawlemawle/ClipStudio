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
  event_type: 'job_progress' | 'media_imported';
  job_id?: string;
  media_id?: string;
  status?: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'ready';
  progress_percent?: number;
  current_step?: string;
  message?: string;
  timestamp: string;
  [key: string]: any;
}

export interface Workspace {
  id: string;
  name: string;
  description: string | null;
  local_storage_path: string;
  created_at: string;
  updated_at: string;
}

export interface ImportedVideo {
  id: string;
  workspace_id: string;
  file_name: string;
  file_path: string;
  file_size_bytes: number;
  duration_seconds: number;
  width: number;
  height: number;
  fps: number;
  video_codec: string;
  audio_codec: string;
  status: string;
  sha256?: string | null;
  container_format: string;
  metadata_json?: string | null;
  created_at: string;
  updated_at: string;
}

export interface MediaListResponse {
  items: ImportedVideo[];
  total: number;
  skip: number;
  limit: number;
}

export interface UploadSession {
  id: string;
  workspace_id: string;
  original_filename: string;
  expected_size_bytes: number;
  received_size_bytes: number;
  status: string;
  chunk_count: number;
  last_chunk_index: number;
  sha256?: string | null;
  expires_at: string;
  created_at: string;
  updated_at: string;
}

export interface UploadCompleteResponse {
  status: 'completed' | 'duplicate_detected' | 'error';
  video?: ImportedVideo | null;
  duplicate_video_id?: string | null;
  message?: string | null;
}
