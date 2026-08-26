import { requestJson } from './client';
import type { LoadingResult } from './types/LoadingResult';
import { validateLoadingResult } from '../adapters/loadingResultAdapter';

export interface LoadingJobRequest { container: unknown; sku: unknown[]; mode?: string }

const LOADING_JOB_TIMEOUT_MS = 300000;

export const LoadingAPI = {
  async createJob(input: LoadingJobRequest): Promise<{ job_id: string }> {
    return requestJson(
      '/loading/jobs',
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input) },
      LOADING_JOB_TIMEOUT_MS,
    );
  },
  async getResult(jobId: string): Promise<LoadingResult> {
    const value = await requestJson<unknown>(`/loading/${encodeURIComponent(jobId)}`);
    return validateLoadingResult(value);
  },
  async getHighlight(jobId: string, type: 'sku'|'wall'|'step'|'object', id: string): Promise<unknown> {
    return requestJson(`/loading/${encodeURIComponent(jobId)}/highlight?type=${type}&id=${encodeURIComponent(id)}`);
  },
};
