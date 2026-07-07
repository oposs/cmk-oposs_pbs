class _Rec:
    def __init__(self, *a, **k):
        self.args = a
        self.kwargs = k


Dictionary = DictElement = Integer = Float = String = BooleanChoice = _Rec
SimpleLevels = LevelDirection = DefaultValue = Password = _Rec
CascadingSingleChoice = CascadingSingleChoiceElement = _Rec
SingleChoice = SingleChoiceElement = List = TimeSpan = TimeMagnitude = _Rec
RegularExpression = validators = _Rec
Percentage = _Rec

MatchingScope = type("MatchingScope", (), {"PREFIX": 0, "INFIX": 1, "FULL": 2})
LevelsType = type("LevelsType", (), {"NONE": 0, "FIXED": 1})


class _V:  # validators namespace
    LengthInRange = NetworkPort = NumberInRange = _Rec


validators = _V()
