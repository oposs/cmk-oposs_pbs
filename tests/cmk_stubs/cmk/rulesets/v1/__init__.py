class _Str(str):
    def __new__(cls, s=""): return super().__new__(cls, s)


def Title(s=""): return _Str(s)
def Help(s=""): return _Str(s)
def Label(s=""): return _Str(s)
def Message(s=""): return _Str(s)
