from abc import ABC, abstractmethod

from src.base_feature import AbstractBaseFeature
from src.radio.events import IncomingTextMessage


class AbstractResponder(AbstractBaseFeature, ABC):
    @abstractmethod
    def handle_packet(self, message: IncomingTextMessage) -> bool:
        """Handle an inbound text message; return True if the responder fired."""
