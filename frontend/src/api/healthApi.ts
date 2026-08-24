import { BackendStatus, requestJson } from './client';

export async function checkBackendHealth(): Promise<BackendStatus> {
  try {
    const result = await requestJson<{ status: string }>('/loading/health', {}, 5000);
    return result.status === 'ok' || result.status === 'healthy' ? BackendStatus.ONLINE : BackendStatus.OFFLINE;
  } catch { return BackendStatus.OFFLINE; }
}
