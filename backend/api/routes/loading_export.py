"""Stable export manifest; file production belongs to a later export stage."""

def get_export(record):
    job=record["id"]
    return {"version":"BLK007C","layout_file":f"{job}_layout.json",
            "sequence_file":f"{job}_sequence.json","job_id":job}
