from .types import DirectionScore


class DirectionScoreEngine:
    weights = {"transportSafety": .30, "wallContinuity": .25, "spaceEfficiency": .20,
               "doorSafety": .15, "layerCompatibility": .10}

    def score(self, space, continuity, transport, door, layer, risk):
        value = (.20 * space + .25 * continuity + .30 * transport + .15 * door + .10 * layer - .10 * risk)
        return DirectionScore(round(space, 4), round(continuity, 4), round(transport, 4),
                              round(door, 4), round(layer, 4), round(risk, 4), round(value, 4))
