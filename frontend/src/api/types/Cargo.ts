export interface Cargo {
  id: string;
  sku: string;
  name: string;
  weight_kg: number;
  position: { x: number; y: number; z: number };
  productDimensions: { length: number; width: number; height: number };
  occupiedDimensions: { width: number; depth: number; height: number };
  axisDefinition: { lengthAxis: 'X' | 'Y' | 'Z'; widthAxis: 'X' | 'Y' | 'Z'; heightAxis: 'X' | 'Y' | 'Z' };
  /** @deprecated BLK007C compatibility alias for occupiedDimensions. */
  size: { w: number; d: number; h: number };
  rotation: { x: number; y: number; z: number; unit: 'rad'; orientation: string };
  material: { color: string; opacity: number };
  loading: { wall: string; layer: string; row: string; step: number; phase: string };
  stability: { group_id: string | null };
  context: string;
}
