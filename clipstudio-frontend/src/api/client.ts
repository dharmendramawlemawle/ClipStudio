import { HealthResponse, ProcessingJob, Workspace } from '../types';

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
