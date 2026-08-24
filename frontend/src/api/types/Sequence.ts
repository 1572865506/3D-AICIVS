export type SequenceAction = 'PLACE' | 'PLACE_GROUP';

export interface SequenceStep {
  step: number;
  action: SequenceAction;
  placements: string[];
  phase: string;
  wall: string;
  row: string;
  layer: string;
  group?: { id: string; type: string; reason: string; objects: string[] };
}

export interface LoadingSequence {
  feasible: boolean;
  steps: SequenceStep[];
  total_steps: number;
  loading_mode: string;
  deterministic_signature: string;
}
