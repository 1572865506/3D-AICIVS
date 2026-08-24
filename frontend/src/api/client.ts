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
  | 'INVALID_RESULT'
  | 'SCHEMA_ERROR';

export class BackendError extends Error {
  constructor(public readonly type: BackendErrorType, message: string, public readonly status?: number) {
    super(message);
    this.name = 'BackendError';
  }
}

export async function requestJson<T>(path: string, init: RequestInit = {}, timeoutMs = 30000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${API_BASE}${path}`, { ...init, signal: controller.signal });
    if (!response.ok) throw new BackendError('SERVER_ERROR', `HTTP ${response.status}`, response.status);
    try { return await response.json() as T; }
    catch { throw new BackendError('INVALID_RESULT', 'Backend returned non-JSON content'); }
  } catch (error) {
    if (error instanceof BackendError) throw error;
    if ((error as Error).name === 'AbortError') throw new BackendError('TIMEOUT', 'Backend request timed out');
    throw new BackendError('NETWORK_ERROR', (error as Error).message || 'Network request failed');
  } finally { clearTimeout(timer); }
}
