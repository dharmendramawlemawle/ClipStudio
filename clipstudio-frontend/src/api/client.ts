import {
  HealthResponse,
  ProcessingJob,
  Workspace,
  ImportedVideo,
  MediaListResponse,
  UploadSession,
  UploadCompleteResponse,
} from '../types';

const API_BASE = '/api/v1';

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) {
    throw new Error(`Health check failed with status ${res.status}`);
  }
  return res.json();
}

export async function fetchJobs(limit: number = 20): Promise<ProcessingJob[]> {
  const res = await fetch(`${API_BASE}/jobs?limit=${limit}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch jobs: ${res.statusText}`);
  }
  return res.json();
}

export async function triggerTestJob(payload?: Record<string, any>): Promise<ProcessingJob> {
  const res = await fetch(`${API_BASE}/jobs/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || { initiated_from: 'browser_ui' }),
  });
  if (!res.ok) {
    throw new Error(`Failed to trigger test job: ${res.statusText}`);
  }
  return res.json();
}

export async function cancelJob(jobId: string): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE}/jobs/${jobId}/cancel`, {
    method: 'POST',
  });
  if (!res.ok) {
    throw new Error(`Failed to cancel job: ${res.statusText}`);
  }
  return res.json();
}

export async function fetchWorkspaces(): Promise<Workspace[]> {
  const res = await fetch(`${API_BASE}/workspaces`);
  if (!res.ok) {
    throw new Error(`Failed to fetch workspaces: ${res.statusText}`);
  }
  return res.json();
}

export async function createWorkspace(data: { name: string; description?: string }): Promise<Workspace> {
  const res = await fetch(`${API_BASE}/workspaces`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      ...data,
      local_storage_path: 'data/media',
    }),
  });
  if (!res.ok) {
    throw new Error(`Failed to create workspace: ${res.statusText}`);
  }
  return res.json();
}

// --- Media & Chunked Upload APIs ---

export async function fetchMedia(
  workspaceId?: string,
  skip: number = 0,
  limit: number = 50,
): Promise<MediaListResponse> {
  const params = new URLSearchParams();
  if (workspaceId) params.append('workspace_id', workspaceId);
  params.append('skip', skip.toString());
  params.append('limit', limit.toString());

  const res = await fetch(`${API_BASE}/media?${params.toString()}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch media: ${res.statusText}`);
  }
  return res.json();
}

export async function fetchMediaById(mediaId: string): Promise<ImportedVideo> {
  const res = await fetch(`${API_BASE}/media/${mediaId}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch media details: ${res.statusText}`);
  }
  return res.json();
}

export async function deleteMedia(mediaId: string): Promise<{ status: string; media_id: string }> {
  const res = await fetch(`${API_BASE}/media/${mediaId}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Failed to delete media (${res.status})`);
  }
  return res.json();
}

export async function initiateUpload(
  workspaceId: string,
  filename: string,
  fileSizeBytes: number,
): Promise<UploadSession> {
  const res = await fetch(`${API_BASE}/media/uploads/initiate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      workspace_id: workspaceId,
      filename,
      file_size_bytes: fileSizeBytes,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Failed to initiate upload (${res.status})`);
  }
  return res.json();
}

export async function uploadChunk(
  uploadId: string,
  chunkIndex: number,
  offsetBytes: number,
  chunkBlob: Blob,
  signal?: AbortSignal,
): Promise<{ received_size_bytes: number; is_complete: boolean }> {
  const res = await fetch(
    `${API_BASE}/media/uploads/${uploadId}/chunk?chunk_index=${chunkIndex}&offset_bytes=${offsetBytes}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: chunkBlob,
      signal,
    },
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Failed to upload chunk ${chunkIndex} (${res.status})`);
  }
  return res.json();
}

export async function completeUpload(
  uploadId: string,
  confirmDuplicate: boolean = false,
): Promise<UploadCompleteResponse> {
  const res = await fetch(`${API_BASE}/media/uploads/${uploadId}/complete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirm_duplicate: confirmDuplicate }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Validation or completion failed (${res.status})`);
  }
  return res.json();
}
