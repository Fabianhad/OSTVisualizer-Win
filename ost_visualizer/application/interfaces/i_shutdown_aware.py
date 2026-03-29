from abc import ABC, abstractmethod


class IShutdownAware(ABC):
    @abstractmethod
    def shutdown(self) -> None:
        raise NotImplementedError
