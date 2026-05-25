class SingleCallRecorder:
    def __init__(self, wrapped=None):
        self.wrapped = wrapped
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.wrapped is None:
            return None
        return self.wrapped(*args, **kwargs)

    @property
    def call_count(self):
        return len(self.calls)

    def assert_called_once(self, test_case, label="user action"):
        test_case.assertEqual(
            self.call_count,
            1,
            f"{label} should call its command once; calls={self.calls!r}",
        )
