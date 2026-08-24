from .types import WallPattern
class WallPatternGenerator:
    def generate(self,wall):
        base=[WallPattern(f"{wall.wall_id}_ORIGINAL",wall.wall_id,"ORIGINAL","preserve_valid_structure"),
              WallPattern(f"{wall.wall_id}_CONTACT",wall.wall_id,"CONTACT_ALIGNED","eliminate_internal_side_gap"),
              WallPattern(f"{wall.wall_id}_LAYER",wall.wall_id,"LAYER_CONTINUOUS","improve_layer_completion")]
        if wall.display_wall:base.append(WallPattern(f"{wall.wall_id}_DISPLAY",wall.wall_id,"CONTINUOUS_DISPLAY","preserve_short_edge_display_grid"))
        return tuple(base)
