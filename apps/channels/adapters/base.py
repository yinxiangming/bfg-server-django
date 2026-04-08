# -*- coding: utf-8 -*-
from abc import ABC, abstractmethod


class ChannelAdapter(ABC):
    """Abstract base class for all channel adapters."""

    #: Declare field mapping spec for each channel (used by frontend preview/validation)
    FIELD_SPEC: dict = {}

    def __init__(self, channel):
        self.channel = channel

    @abstractmethod
    def validate_credentials(self) -> bool:
        """Test that stored credentials can authenticate successfully."""

    @abstractmethod
    def map_product(self, product) -> dict:
        """Map an internal Product to the channel-specific payload dict."""

    @abstractmethod
    def publish(self, product) -> str:
        """Publish product to the channel; return the external listing ID."""

    @abstractmethod
    def update(self, listing) -> None:
        """Update an existing listing with the latest product data."""

    @abstractmethod
    def end(self, listing) -> None:
        """End/withdraw an active listing."""

    @abstractmethod
    def relist(self, listing) -> str:
        """Relist an ended listing; return the new external listing ID."""

    @abstractmethod
    def fetch_feedback(self, listing) -> list:
        """Return a list of feedback dicts for the given listing."""

    @abstractmethod
    def fetch_questions(self, listing) -> list:
        """Return a list of question dicts for the given listing."""

    @abstractmethod
    def post_answer(self, question, answer: str) -> None:
        """Post an answer to a buyer question on the channel."""
