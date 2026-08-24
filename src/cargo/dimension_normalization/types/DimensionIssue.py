from dataclasses import asdict,dataclass

@dataclass(frozen=True)
class DimensionIssue:
    code:str;severity:str;message:str;axis:str|None=None
    def to_dict(self):return asdict(self)
