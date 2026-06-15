from abc import ABC, abstractmethod


class BaseModelFactory(ABC):
    @abstractmethod
    def generator(self):
        pass