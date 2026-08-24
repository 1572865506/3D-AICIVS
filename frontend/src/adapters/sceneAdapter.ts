import type { LoadingResult, SceneObject } from '../api/types/LoadingResult';

export interface ThreeSceneObject {
  uuid: string;
  position: [number, number, number];
  scale: [number, number, number];
  rotation: [number, number, number];
  material: { color: string; opacity: number };
  metadata: SceneObject['metadata'];
}

export function adaptScene(result: LoadingResult): ThreeSceneObject[] {
  return result.scene.objects.map(object => ({
    uuid: object.uuid,
    position: object.position,
    scale: object.scale,
    rotation: object.rotation,
    material: object.style,
    metadata: object.metadata,
  }));
}
