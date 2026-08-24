"""
Multi-start heuristic generator and strategy manager for Solver V2 (Agent 09).
Provides diverse packing heuristics and priority permutations to explore distinct solution regions.
"""
from dataclasses import dataclass
from enum import Enum
from typing import List, Dict, Any, Optional, Tuple
import random

from backend.solver_v2.domain.models import CargoSKU, PackingRole, CargoClass


class StartStrategy(str, Enum):
    LARGEST_VOLUME_FIRST = "LARGEST_VOLUME_FIRST"
    HIGHEST_DENSITY_FIRST = "HIGHEST_DENSITY_FIRST"
    LARGEST_FOOTPRINT_FIRST = "LARGEST_FOOTPRINT_FIRST"
    FOUNDATION_REINFORCED = "FOUNDATION_REINFORCED"
    WALL_HOMOGENEOUS = "WALL_HOMOGENEOUS"
    STOCHASTIC_PERTURBED = "STOCHASTIC_PERTURBED"


@dataclass
class MultiStartConfig:
    """Strategy configuration for a single multi-start run."""
    strategy: StartStrategy
    seed: int
    score_weights_perturbation: Dict[str, float]
    sku_priority_order: List[str]


class MultiStartManager:
    """
    Generates varied multi-start strategies for hierarchical search exploration.
    """

    @staticmethod
    def generate_strategies(
        cargo_list: List[CargoSKU],
        num_runs: int = 3,
        base_seed: int = 42,
    ) -> List[MultiStartConfig]:
        """
        Generates a sequence of distinct MultiStartConfig instances.
        """
        strategies: List[MultiStartConfig] = []
        strategy_types = [
            StartStrategy.LARGEST_VOLUME_FIRST,
            StartStrategy.FOUNDATION_REINFORCED,
            StartStrategy.HIGHEST_DENSITY_FIRST,
            StartStrategy.LARGEST_FOOTPRINT_FIRST,
            StartStrategy.WALL_HOMOGENEOUS,
            StartStrategy.STOCHASTIC_PERTURBED,
        ]

        for i in range(num_runs):
            stype = strategy_types[i % len(strategy_types)]
            run_seed = base_seed + i * 10007
            rng = random.Random(run_seed)

            # Determine SKU priority ordering
            prioritized_skus = MultiStartManager._order_skus(cargo_list, stype, rng)
            sku_ids = [s.sku_id for s in prioritized_skus]

            # Generate weight perturbation
            if stype == StartStrategy.STOCHASTIC_PERTURBED:
                perturbations = {
                    "w_contact": rng.uniform(15.0, 35.0),
                    "w_gravity": rng.uniform(20.0, 40.0),
                    "w_smoothness": rng.uniform(10.0, 25.0),
                    "w_frag": rng.uniform(10.0, 30.0),
                }
            else:
                perturbations = {}

            strategies.append(
                MultiStartConfig(
                    strategy=stype,
                    seed=run_seed,
                    score_weights_perturbation=perturbations,
                    sku_priority_order=sku_ids,
                )
            )

        return strategies

    @staticmethod
    def _order_skus(
        cargo_list: List[CargoSKU],
        strategy: StartStrategy,
        rng: random.Random,
    ) -> List[CargoSKU]:
        """Orders SKUs based on the given strategy."""
        skus = list(cargo_list)

        if strategy == StartStrategy.LARGEST_VOLUME_FIRST:
            return sorted(skus, key=lambda s: (s.box.volume, s.weight_kg), reverse=True)

        elif strategy == StartStrategy.HIGHEST_DENSITY_FIRST:
            return sorted(
                skus,
                key=lambda s: (s.weight_kg / max(0.001, s.box.volume), s.box.volume),
                reverse=True,
            )

        elif strategy == StartStrategy.LARGEST_FOOTPRINT_FIRST:
            return sorted(
                skus,
                key=lambda s: (s.box.x * s.box.y, s.box.volume),
                reverse=True,
            )

        elif strategy == StartStrategy.FOUNDATION_REINFORCED:
            def foundation_key(s: CargoSKU) -> Tuple[int, float, float]:
                is_heavy = 1 if (PackingRole.FOUNDATION in s.packing_roles or s.cargo_class == CargoClass.HEAVY) else 0
                return (is_heavy, s.weight_kg, s.box.volume)
            return sorted(skus, key=foundation_key, reverse=True)

        elif strategy == StartStrategy.WALL_HOMOGENEOUS:
            # Sort by required quantity descending to form solid homogeneous walls
            return sorted(skus, key=lambda s: (s.quantity.required, s.box.volume), reverse=True)

        elif strategy == StartStrategy.STOCHASTIC_PERTURBED:
            # Random shuffle with slight volume bias
            weighted = [(s.box.volume * rng.uniform(0.5, 1.5), s) for s in skus]
            weighted.sort(key=lambda item: item[0], reverse=True)
            return [s for _, s in weighted]

        return skus
