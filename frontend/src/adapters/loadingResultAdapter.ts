import { BackendError } from '../api/client';
import type { LoadingResult } from '../api/types/LoadingResult';

export function validateLoadingResult(value: unknown): LoadingResult {
  if (!value || typeof value !== 'object') throw new BackendError('SCHEMA_ERROR', 'LoadingResult must be an object');
  const v = value as Record<string, unknown>;
  const required = ['version', 'container', 'cargo', 'scene', 'sequence', 'repair'];
  const missing = required.filter(key => !(key in v));
  if (missing.length) throw new BackendError('SCHEMA_ERROR', `LoadingResult missing: ${missing.join(', ')}`);
  if (v.version !== 'BLK007C') throw new BackendError('SCHEMA_ERROR', `Unsupported LoadingResult version: ${String(v.version)}`);
  if (!Array.isArray(v.cargo) || !Array.isArray((v.scene as Record<string, unknown>)?.objects)) {
    throw new BackendError('SCHEMA_ERROR', 'Cargo/scene collections are invalid');
  }
  for (const item of v.cargo as Array<Record<string, unknown>>) {
    const product = item.productDimensions as Record<string, unknown> | undefined;
    const occupied = item.occupiedDimensions as Record<string, unknown> | undefined;
    const axes = item.axisDefinition as Record<string, unknown> | undefined;
    if (!product || !occupied || !axes ||
        !['length', 'width', 'height'].every(key => Number(product[key]) > 0) ||
        !['width', 'depth', 'height'].every(key => Number(occupied[key]) > 0)) {
      throw new BackendError('SCHEMA_ERROR', 'Cargo dimension schema is invalid');
    }
  }
  return value as LoadingResult;
}
