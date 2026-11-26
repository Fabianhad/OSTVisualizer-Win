class Raised:
    def __init__(self, error_type, message):
        self.error_type = error_type
        self.message = message

    def __eq__(self, other):
        if not isinstance(other, BaseException):
            return NotImplemented
        expected = (
            self.error_type
            if isinstance(self.error_type, str)
            else self.error_type.__name__
        )
        return type(other).__name__ == expected and str(other) == self.message

    def __ne__(self, other):
        result = self.__eq__(other)
        return result if result is NotImplemented else not result

    def __repr__(self):
        name = (
            self.error_type
            if isinstance(self.error_type, str)
            else self.error_type.__name__
        )
        return f"Raised({name}, {self.message!r})"
