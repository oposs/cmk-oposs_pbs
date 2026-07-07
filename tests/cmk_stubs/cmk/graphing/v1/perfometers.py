class _Rec:
    def __init__(self, *a, **k):
        self.args = a
        self.kwargs = k


Perfometer = FocusRange = Closed = _Rec
