import type { AnimationFrame, LoadingResult } from '../api/types/LoadingResult';

export interface LoadingAnimation extends AnimationFrame {}

export function adaptAnimation(result: LoadingResult): LoadingAnimation[] {
  return result.animation.frames.map(frame => ({ ...frame, movements: frame.movements.map(movement => ({ ...movement })) }));
}
