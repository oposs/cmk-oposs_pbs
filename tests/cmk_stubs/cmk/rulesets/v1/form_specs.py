class _Rec:
    def __init__(self, *a, **k):
        self.args = a
        self.kwargs = k


Dictionary = DictElement = Integer = Float = String = BooleanChoice = _Rec
SimpleLevels = DefaultValue = Password = _Rec
CascadingSingleChoice = CascadingSingleChoiceElement = _Rec
SingleChoice = SingleChoiceElement = List = TimeSpan = _Rec
RegularExpression = validators = _Rec
Percentage = _Rec

MatchingScope = type("MatchingScope", (), {"PREFIX": 0, "INFIX": 1, "FULL": 2})
LevelsType = type("LevelsType", (), {"NONE": 0, "FIXED": 1})
LevelDirection = type("LevelDirection", (), {"UPPER": 0, "LOWER": 1})
TimeMagnitude = type("TimeMagnitude", (), {
    "MILLISECOND": 0, "SECOND": 1, "MINUTE": 2, "HOUR": 3, "DAY": 4})


class _V:  # validators namespace
    LengthInRange = NetworkPort = NumberInRange = _Rec


validators = _V()
