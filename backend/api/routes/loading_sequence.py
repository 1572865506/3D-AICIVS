"""Sequence, animation, camera, and highlight projections."""
from backend.api.adapters import SceneAdapter

def get_sequence(record):return record["sequence"]
def get_animation(record):return record["animation"]
def get_camera(record):return record["camera"]
def get_highlight(record,kind,value):
    return SceneAdapter.highlight(record["cargo"],record["walls"],record["sequence"],kind,value)
