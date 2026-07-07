class _Rec:
    def __init__(self, *a, **k):
        self.args = a
        self.kwargs = k


Metric = Unit = DecimalNotation = IECNotation = TimeNotation = _Rec

Color = type("Color", (), {
    n: i for i, n in enumerate(
        ["LIGHT_BLUE", "LIGHT_PURPLE", "BLUE", "GREEN", "ORANGE", "RED", "CYAN", "PURPLE", "GRAY"]
    )
})
