export const API_BASE = import.meta.env.VITE_LOADING_API_URL;

export enum BackendStatus {
  ONLINE = 'ONLINE',
  OFFLINE = 'OFFLINE',
  CHECKING = 'CHECKING',
}

export type BackendErrorType =
  | 'NETWORK_ERROR'
  | 'TIMEOUT'
  | 'SERVER_ERROR'
  | 'INPUT_CONSTRAINT'
  | 'INVALID_RESULT'
  | 'SCHEMA_ERROR';

export class BackendError extends Error {
  constructor(public readonly type: BackendErrorType, message: string, public readonly status?: number, public readonly details?: unknown) {
    super(message);
    this.name = 'BackendError';
  }
}

export async function requestJson<T>(path: string, init: RequestInit = {}, timeoutMs = 30000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${API_BASE}${path}`, { ...init, signal: controller.signal });
    if (!response.ok) {
      let details: any = null;
      try { details = await response.json(); } catch { /* non-JSON error response */ }
      const message = details?.error || details?.message;
      const errorType: BackendErrorType = response.status === 422 ||
        (details && typeof details === 'object' && (details as { category?: string }).category === 'INPUT_CONSTRAINT')
        ? 'INPUT_CONSTRAINT' : 'SERVER_ERROR';
      throw new BackendError(errorType, message ? `HTTP ${response.status}: ${message}` : `HTTP ${response.status}`, response.status, details);
    }
    try { return await response.json() as T; }
    catch { throw new BackendError('INVALID_RESULT', 'Backend returned non-JSON content'); }
  } catch (error) {
    if (error instanceof BackendError) throw error;
    if ((error as Error).name === 'AbortError') throw new BackendError('TIMEOUT', 'Backend request timed out');
    throw new BackendError('NETWORK_ERROR', (error as Error).message || 'Network request failed');
  } finally { clearTimeout(timer); }
}
