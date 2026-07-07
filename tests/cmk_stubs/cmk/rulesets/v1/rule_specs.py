class _Rec:
    def __init__(self, *a, **k):
        self.args = a
        self.kwargs = k


CheckParameters = SpecialAgent = HostCondition = HostAndItemCondition = _Rec


class Topic:
    STORAGE = _Rec()
    GENERAL = _Rec()
