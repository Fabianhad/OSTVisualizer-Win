from abc import ABC, abstractmethod


class IStartable(ABC):
    @abstractmethod
    def start(self) -> None: ...
