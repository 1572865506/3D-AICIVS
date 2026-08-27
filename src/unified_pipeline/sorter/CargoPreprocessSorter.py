"""
Preprocess Sorter & Monolithic Cross-Section Recipe Formulator.

Implements:
1. Multi-attribute priority ranking (Zone potential, mass density gradient, total volume).
2. Stack-First Monolithic Dense Block formulation with Zero Tail Abandonment.
3. Vertical Headspace Stack Relay (台阶顶层空间回填): Whenever a base block or tail row has height Z < 2.50m,
   compatible subsequent SKUs are stacked on top to reach full 2.69m container height.
4. Full-Depth Flank Pairing with Proximity Affinity across exact same slab depth Delta X.
5. Multi-SKU Composite Tail Sections for 100% inventory absorption.
"""
from dataclasses import dataclass, field
import math
from typing import Dict, List, Optional, Tuple

from src.unified_pipeline.model.UnifiedCargoModel import (
    UnifiedCargoModel,
    ZonePreference,
    PackingRole,
    OrientationOption
)


@dataclass
class SectionSubBlock:
    sku_id: str
    orientation_name: str
    dx: float
    dy: float
    dz: float
    cols_y: int
    rows_x: int
    layers_z: int
    count: int
    offset_y: float
    offset_z: float
    offset_x: float = 0.0
    tag: str = "PRIMARY"


@dataclass
class MonolithicSectionRecipe:
    recipe_id: str
    primary_sku_id: str
    sub_blocks: List[SectionSubBlock] = field(default_factory=list)
    depth_dx: float = 0.0
    width_dy: float = 2.35
    height_dz: float = 0.0
    total_boxes: int = 0
    utilization_2d: float = 0.0
    is_tail_section: bool = False

    @property
    def primary_block(self) -> SectionSubBlock:
        return self.sub_blocks[0] if self.sub_blocks else None


class CargoPreprocessSorter:
    def __init__(self, container_length: float = 12.024, container_width: float = 2.350, container_height: float = 2.690):
        self.container_l = container_length
        self.container_w = container_width
        self.container_h = container_height

    def calculate_priorities(self, cargo_list: List[UnifiedCargoModel]) -> List[UnifiedCargoModel]:
        """Calculates global priority scores and sorts cargo by longitudinal loading order."""
        for c in cargo_list:
            zone_bonus = 0.0
            if c.zone_preference == ZonePreference.INNER:
                zone_bonus = 2000.0
            elif c.zone_preference == ZonePreference.MIDDLE:
                zone_bonus = 1000.0
            elif c.zone_preference == ZonePreference.DOOR:
                zone_bonus = 100.0
            else:
                zone_bonus = 500.0

            # Density bonus (heavy goods at bottom/inner)
            density_bonus = min(c.density_kg_m3 * 0.5, 300.0)
            
            # Bulk volume bonus (large batches form solid monolithic walls first)
            total_vol = c.volume_m3 * c.quantity_required
            volume_bonus = min(total_vol * 20.0, 500.0)

            c.priority_score = round(zone_bonus + density_bonus + volume_bonus, 2)

        cargo_list.sort(key=lambda x: x.priority_score, reverse=True)
        return cargo_list

    def _fill_vertical_headspace(
        self,
        dx: float,
        dy: float,
        offset_x: float,
        offset_y: float,
        base_z: float,
        avail_height_dz: float,
        sorted_cargo: List[UnifiedCargoModel],
        remaining_qty: Dict[str, int]
    ) -> List[SectionSubBlock]:
        """
        Stacks compatible subsequent SKUs on top of a lower base platform (base_z)
        to complete the full container height (up to 2.69m), eliminating empty steps.
        """
        top_blocks: List[SectionSubBlock] = []
        cur_z = base_z

        for cand in sorted_cargo:
            c_id = cand.sku_id
            avail = remaining_qty.get(c_id, 0)
            if avail <= 0:
                continue

            rem_h = (self.container_h - 0.05) - cur_z
            if rem_h < 0.10:
                break

            for opt in cand.orientations:
                if opt.dx <= dx + 1e-4 and opt.dy <= dy + 1e-4 and opt.dz <= rem_h + 1e-4:
                    rows_x = int((dx + 1e-4) / opt.dx)
                    cols_y = int((dy + 1e-4) / opt.dy)
                    layers_z = int((rem_h + 1e-4) / opt.dz)
                    if cand.max_stack_layers:
                        layers_z = min(layers_z, cand.max_stack_layers)
                    
                    if rows_x <= 0 or cols_y <= 0 or layers_z <= 0:
                        continue

                    needed = rows_x * cols_y * layers_z
                    if needed > avail:
                        layers_z = avail // (rows_x * cols_y)
                        if layers_z > 0:
                            needed = rows_x * cols_y * layers_z
                        else:
                            layers_z = 1
                            rows_x = 1
                            cols_y = min(cols_y, avail)
                            needed = cols_y
                    
                    if needed <= 0 or needed > avail:
                        continue

                    block = SectionSubBlock(
                        sku_id=c_id,
                        orientation_name=opt.name,
                        dx=opt.dx,
                        dy=opt.dy,
                        dz=opt.dz,
                        cols_y=cols_y,
                        rows_x=rows_x,
                        layers_z=layers_z,
                        count=needed,
                        offset_y=offset_y,
                        offset_z=round(cur_z, 4),
                        offset_x=offset_x,
                        tag="TOP_RELAY"
                    )
                    top_blocks.append(block)
                    remaining_qty[c_id] -= needed
                    cur_z = round(cur_z + layers_z * opt.dz, 4)
                    break
        return top_blocks

    def generate_monolithic_recipes(self, cargo_list: List[UnifiedCargoModel]) -> Tuple[List[MonolithicSectionRecipe], Dict[str, int]]:
        """
        Generates monolithic cross-section recipes with full-height vertical stacking:
        1. Form primary monolithic solid blocks for each SKU.
        2. If block height < 2.50m or if a low tail step is added, stack subsequent SKUs on top!
        3. Pair flank items matching the exact depth Delta X.
        4. Assemble residual tails into Composite Sections.
        """
        sorted_cargo = self.calculate_priorities(cargo_list)
        remaining_qty: Dict[str, int] = {c.sku_id: c.quantity_required for c in sorted_cargo}
        
        recipes: List[MonolithicSectionRecipe] = []
        recipe_idx = 1

        # Phase 1: Primary monolithic walls with full-height stacking
        for c in sorted_cargo:
            sku_id = c.sku_id
            if remaining_qty[sku_id] <= 0:
                continue

            upright_opts = [o for o in c.orientations if o.is_upright] or c.orientations
            upright_opts.sort(key=lambda o: (int(self.container_w / o.dy) * o.dy), reverse=True)
            best_opt = upright_opts[0]
            
            cols_y = max(1, int(self.container_w / best_opt.dy))
            layers_z = int((self.container_h - 0.05) / best_opt.dz)
            if c.max_stack_layers:
                layers_z = min(layers_z, c.max_stack_layers)
            layers_z = max(1, layers_z)

            per_row_count = cols_y * layers_z
            avail = remaining_qty[sku_id]

            complete_rows = avail // per_row_count
            tail_qty = avail % per_row_count

            if complete_rows > 0 or tail_qty >= cols_y:
                sub_blocks: List[SectionSubBlock] = []
                slab_rows = max(1, min(complete_rows, 4))
                primary_count = slab_rows * per_row_count
                
                if primary_count > avail:
                    slab_rows = 1
                    layers_z = max(1, avail // cols_y)
                    primary_count = cols_y * layers_z
                    tail_qty = avail - primary_count

                slab_depth_dx = round(slab_rows * best_opt.dx, 4)
                primary_width_dy = round(cols_y * best_opt.dy, 4)
                slab_height_dz = round(layers_z * best_opt.dz, 4)

                primary_block = SectionSubBlock(
                    sku_id=sku_id,
                    orientation_name=best_opt.name,
                    dx=best_opt.dx,
                    dy=best_opt.dy,
                    dz=best_opt.dz,
                    cols_y=cols_y,
                    rows_x=slab_rows,
                    layers_z=layers_z,
                    count=primary_count,
                    offset_y=0.0,
                    offset_z=0.0,
                    offset_x=0.0,
                    tag="PRIMARY"
                )
                sub_blocks.append(primary_block)
                remaining_qty[sku_id] -= primary_count

                # If primary block has headspace, stack subsequent goods on top!
                if self.container_h - slab_height_dz >= 0.15:
                    top_relays = self._fill_vertical_headspace(
                        dx=slab_depth_dx,
                        dy=primary_width_dy,
                        offset_x=0.0,
                        offset_y=0.0,
                        base_z=slab_height_dz,
                        avail_height_dz=self.container_h - slab_height_dz,
                        sorted_cargo=sorted_cargo,
                        remaining_qty=remaining_qty
                    )
                    sub_blocks.extend(top_relays)

                # Tail row absorption with top filling
                if tail_qty > 0 and remaining_qty[sku_id] >= tail_qty:
                    tail_layers = max(1, tail_qty // cols_y)
                    actual_tail_count = min(tail_qty, remaining_qty[sku_id])
                    tail_h = round(tail_layers * best_opt.dz, 4)
                    tail_dx = best_opt.dx
                    tail_dy = primary_width_dy
                    tail_offset_x = slab_depth_dx

                    tail_block = SectionSubBlock(
                        sku_id=sku_id,
                        orientation_name=best_opt.name,
                        dx=best_opt.dx,
                        dy=best_opt.dy,
                        dz=best_opt.dz,
                        cols_y=cols_y,
                        rows_x=1,
                        layers_z=tail_layers,
                        count=actual_tail_count,
                        offset_y=0.0,
                        offset_z=0.0,
                        offset_x=tail_offset_x,
                        tag="SELF_TAIL"
                    )
                    sub_blocks.append(tail_block)
                    remaining_qty[sku_id] -= actual_tail_count
                    slab_depth_dx = round(slab_depth_dx + tail_dx, 4)

                    # CRITICAL FIX: Fill headspace above tail step with subsequent SKUs!
                    if self.container_h - tail_h >= 0.15:
                        tail_top_relays = self._fill_vertical_headspace(
                            dx=tail_dx,
                            dy=tail_dy,
                            offset_x=tail_offset_x,
                            offset_y=0.0,
                            base_z=tail_h,
                            avail_height_dz=self.container_h - tail_h,
                            sorted_cargo=sorted_cargo,
                            remaining_qty=remaining_qty
                        )
                        sub_blocks.extend(tail_top_relays)

                # Flank lateral matching across the EXACT same slab depth Delta X
                lateral_gap = round(self.container_w - primary_width_dy, 4)
                if lateral_gap >= 0.05:
                    flank_block = self._find_best_flank_block(
                        lateral_gap=lateral_gap,
                        target_depth_dx=slab_depth_dx,
                        target_height_dz=self.container_h,
                        primary_sku=c,
                        cargo_list=sorted_cargo,
                        remaining_qty=remaining_qty
                    )
                    if flank_block:
                        sub_blocks.append(flank_block)
                        # Fill headspace above flank if not full height
                        flank_h = flank_block.layers_z * flank_block.dz
                        if self.container_h - flank_h >= 0.15:
                            flank_top_relays = self._fill_vertical_headspace(
                                dx=flank_block.rows_x * flank_block.dx,
                                dy=flank_block.cols_y * flank_block.dy,
                                offset_x=flank_block.offset_x,
                                offset_y=flank_block.offset_y,
                                base_z=flank_h,
                                avail_height_dz=self.container_h - flank_h,
                                sorted_cargo=sorted_cargo,
                                remaining_qty=remaining_qty
                            )
                            sub_blocks.extend(flank_top_relays)

                tot_count = sum(b.count for b in sub_blocks)
                recipe = MonolithicSectionRecipe(
                    recipe_id=f"RECIPE_MONO_{recipe_idx:03d}_{sku_id}",
                    primary_sku_id=sku_id,
                    sub_blocks=sub_blocks,
                    depth_dx=slab_depth_dx,
                    width_dy=self.container_w,
                    height_dz=self.container_h,
                    total_boxes=tot_count,
                    utilization_2d=round(primary_width_dy / self.container_w, 4),
                    is_tail_section=False
                )
                recipes.append(recipe)
                recipe_idx += 1

        # Phase 2: Form Composite Tail Sections for residual inventory
        for c in sorted_cargo:
            sku_id = c.sku_id
            avail = remaining_qty[sku_id]
            if avail <= 0:
                continue

            upright_opts = [o for o in c.orientations if o.is_upright] or c.orientations
            opt = upright_opts[0]
            
            cols_y = max(1, min(int(self.container_w / opt.dy), avail))
            layers_z = max(1, min(int((self.container_h - 0.05) / opt.dz), (avail + cols_y - 1) // cols_y))
            rows_x = max(1, (avail + cols_y * layers_z - 1) // (cols_y * layers_z))
            
            actual_count = min(avail, rows_x * cols_y * layers_z)
            slab_depth_dx = round(rows_x * opt.dx, 4)
            slab_width_dy = round(cols_y * opt.dy, 4)
            slab_height_dz = round(layers_z * opt.dz, 4)

            sub_blocks = []
            tail_block = SectionSubBlock(
                sku_id=sku_id,
                orientation_name=opt.name,
                dx=opt.dx,
                dy=opt.dy,
                dz=opt.dz,
                cols_y=cols_y,
                rows_x=rows_x,
                layers_z=layers_z,
                count=actual_count,
                offset_y=0.0,
                offset_z=0.0,
                offset_x=0.0,
                tag="TAIL_SECTION"
            )
            sub_blocks.append(tail_block)
            remaining_qty[sku_id] -= actual_count

            # Fill headspace above this tail block
            if self.container_h - slab_height_dz >= 0.15:
                top_relays = self._fill_vertical_headspace(
                    dx=slab_depth_dx,
                    dy=slab_width_dy,
                    offset_x=0.0,
                    offset_y=0.0,
                    base_z=slab_height_dz,
                    avail_height_dz=self.container_h - slab_height_dz,
                    sorted_cargo=sorted_cargo,
                    remaining_qty=remaining_qty
                )
                sub_blocks.extend(top_relays)

            # Flank pairing
            lateral_gap = round(self.container_w - slab_width_dy, 4)
            if lateral_gap >= 0.05:
                flank_block = self._find_best_flank_block(
                    lateral_gap=lateral_gap,
                    target_depth_dx=slab_depth_dx,
                    target_height_dz=self.container_h,
                    primary_sku=c,
                    cargo_list=sorted_cargo,
                    remaining_qty=remaining_qty
                )
                if flank_block:
                    sub_blocks.append(flank_block)

            tot_count = sum(b.count for b in sub_blocks)
            recipe = MonolithicSectionRecipe(
                recipe_id=f"RECIPE_TAIL_{recipe_idx:03d}_{sku_id}",
                primary_sku_id=sku_id,
                sub_blocks=sub_blocks,
                depth_dx=slab_depth_dx,
                width_dy=self.container_w,
                height_dz=self.container_h,
                total_boxes=tot_count,
                utilization_2d=round(slab_width_dy / self.container_w, 4),
                is_tail_section=True
            )
            recipes.append(recipe)
            recipe_idx += 1

        return recipes, remaining_qty

    def _find_best_flank_block(
        self,
        lateral_gap: float,
        target_depth_dx: float,
        target_height_dz: float,
        primary_sku: UnifiedCargoModel,
        cargo_list: List[UnifiedCargoModel],
        remaining_qty: Dict[str, int]
    ) -> Optional[SectionSubBlock]:
        """
        Finds the optimal flank block to fill lateral_gap with the EXACT same depth target_depth_dx.
        """
        best_score = -1.0
        best_block: Optional[SectionSubBlock] = None

        for cand in cargo_list:
            c_id = cand.sku_id
            avail = remaining_qty.get(c_id, 0)
            if avail <= 0:
                continue

            for opt in cand.orientations:
                if opt.dy > lateral_gap + 1e-4:
                    continue
                cols_y = int((lateral_gap + 1e-4) / opt.dy)
                if cols_y <= 0:
                    continue

                if opt.dx > target_depth_dx + 1e-4:
                    continue
                rows_x = int((target_depth_dx + 1e-4) / opt.dx)
                if rows_x <= 0:
                    continue

                layers_z = int((target_height_dz + 0.1) / opt.dz)
                if cand.max_stack_layers:
                    layers_z = min(layers_z, cand.max_stack_layers)
                if layers_z <= 0:
                    layers_z = 1

                needed = cols_y * rows_x * layers_z
                if needed > avail:
                    layers_z = avail // (cols_y * rows_x)
                    if layers_z > 0:
                        needed = cols_y * rows_x * layers_z
                    else:
                        layers_z = 1
                        rows_x = 1
                        cols_y = min(cols_y, avail)
                        needed = cols_y
                
                if needed <= 0 or needed > avail:
                    continue

                gap_coverage = (cols_y * opt.dy) / lateral_gap
                depth_coverage = (rows_x * opt.dx) / target_depth_dx
                
                affinity_bonus = 1.0 if cand.category == primary_sku.category else 0.5
                if cand.zone_preference == primary_sku.zone_preference:
                    affinity_bonus += 0.5

                score = gap_coverage * 0.5 + depth_coverage * 0.3 + affinity_bonus * 0.2

                if score > best_score:
                    best_score = score
                    best_block = SectionSubBlock(
                        sku_id=c_id,
                        orientation_name=opt.name,
                        dx=opt.dx,
                        dy=opt.dy,
                        dz=opt.dz,
                        cols_y=cols_y,
                        rows_x=rows_x,
                        layers_z=layers_z,
                        count=needed,
                        offset_y=round(self.container_w - lateral_gap, 4),
                        offset_z=0.0,
                        offset_x=0.0,
                        tag="FLANK"
                    )

        if best_block:
            remaining_qty[best_block.sku_id] -= best_block.count

        return best_block
