"""Layout-facing REST product projections."""

def get_layout(record):return record
def get_container(record):return record["container"]
def get_cargo(record):return {"cargo":record["cargo"],"count":len(record["cargo"])}
def get_walls(record):return {"walls":record["walls"],"count":len(record["walls"])}
def get_scene(record):return record["scene"]
