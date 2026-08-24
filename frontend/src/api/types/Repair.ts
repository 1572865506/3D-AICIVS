export interface RepairGroup {
  id: string;
  type: string;
  objects: string[];
  reason: string;
  created_by: string;
  temporary_stability_resolved: boolean;
}

export interface Repair {
  enabled: boolean;
  repaired: boolean;
  groups: RepairGroup[];
  actions: unknown[];
  validation: Record<string, boolean>;
}
