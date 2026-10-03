import threading

_DICT_ACCESS = (
    "__getitem__",
    "__setitem__",
    "__delitem__",
    "__contains__",
    "__iter__",
    "__len__",
    "get",
    "pop",
    "popitem",
    "items",
    "keys",
    "values",
    "setdefault",
    "update",
    "clear",
    "copy",
)
_SET_ACCESS = (
    "__contains__",
    "__iter__",
    "__len__",
    "add",
    "discard",
    "remove",
    "pop",
    "clear",
    "update",
    "difference",
    "intersection",
    "union",
    "issubset",
    "copy",
)


def _guarded_class(base, access_names):
    def wrap(name):
        original = getattr(base, name)

        def method(self, *args, **options):
            if not self._guard_lock.locked():
                raise AssertionError(f"{base.__name__}.{name} used without the lock")
            return original(self, *args, **options)

        method.__name__ = name
        return method

    namespace = {name: wrap(name) for name in access_names}
    return type(f"LockGuarded{base.__name__.title()}", (base,), namespace)


_GuardedDict = _guarded_class(dict, _DICT_ACCESS)
_GuardedSet = _guarded_class(set, _SET_ACCESS)


def guard_mapping(lock: "threading.Lock", mapping: dict) -> dict:
    """Copy of `mapping` that raises AssertionError when touched while `lock` is free."""
    guarded = _GuardedDict(mapping)
    guarded._guard_lock = lock
    return guarded


def guard_set(lock: "threading.Lock", values: set) -> set:
    """Copy of `values` that raises AssertionError when touched while `lock` is free."""
    guarded = _GuardedSet(values)
    guarded._guard_lock = lock
    return guarded
