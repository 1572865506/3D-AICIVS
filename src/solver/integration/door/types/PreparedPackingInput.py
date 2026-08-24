from dataclasses import dataclass
from typing import Tuple

from backend.solver_v2.domain.models import CargoSKU, ContainerSpec
from src.constraints.door.types import DoorWall
from .SolverDoorContext import SolverDoorContext


@dataclass(frozen=True)
class PreparedPackingInput:
    original_container: ContainerSpec
    solver_container: ContainerSpec
    original_cargo: Tuple[CargoSKU, ...]
    solver_cargo: Tuple[CargoSKU, ...]
    door_context: SolverDoorContext
    door_wall: DoorWall
