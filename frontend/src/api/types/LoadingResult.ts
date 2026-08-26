import type { Cargo } from './Cargo';
import type { LoadingSequence } from './Sequence';
import type { Repair } from './Repair';

export interface SceneObject {
  uuid: string;
  type: 'CARGO';
  position: [number, number, number];
  scale: [number, number, number];
  rotation: [number, number, number];
  style: { color: string; opacity: number };
  metadata: { sku: string; step: number; wall: string; orientation?: string };
}

export interface AnimationFrame {
  step: number;
  objects: string[];
  from: [number, number, number];
  to: [number, number, number];
  movements: Array<{ object: string; from: [number, number, number]; to: [number, number, number] }>;
  duration: number;
  coordinate_space: string;
}

export interface LoadingResult {
  id: string;
  version: 'BLK007C';
  container: Record<string, unknown>;
  cargo: Cargo[];
  walls: unknown[];
  sequence: LoadingSequence;
  repair: Repair;
  scene: { coordinate_space: string; objects: SceneObject[]; container_bounds: unknown };
  animation: { frames: AnimationFrame[]; total_frames: number; playback: unknown };
  camera: { position: [number, number, number]; target: [number, number, number]; zoom: number; up: [number, number, number] };
  metrics: Record<string, number | boolean>;
}
