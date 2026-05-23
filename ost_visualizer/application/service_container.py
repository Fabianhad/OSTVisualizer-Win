from typing import Any, Callable, Dict, List, Type


class ServiceContainer:
    def __init__(self):
        self._services: Dict[str, Any] = {}
        self._factories: Dict[str, Callable] = {}
        self._singletons: Dict[str, Any] = {}

    def register_instance(self, name: str, instance: Any):
        self._services[name] = instance

    def register_singleton(self, name: str, factory: Callable):
        self._factories[name] = factory
        self._singletons[name] = None

    def get(self, name: str) -> Any:
        if name in self._services:
            return self._services[name]
        if name in self._singletons:
            if self._singletons[name] is None:
                self._singletons[name] = self._factories[name]()
            return self._singletons[name]
        if name in self._factories:
            return self._factories[name]()
        raise KeyError(f"Service '{name}' not found")

    def get_by_interface(self, iface: Type) -> List[Any]:
        results = []
        for svc in self._services.values():
            if isinstance(svc, iface):
                results.append(svc)
        for name, singleton in self._singletons.items():
            if singleton is not None and isinstance(singleton, iface):
                results.append(singleton)
        return results
