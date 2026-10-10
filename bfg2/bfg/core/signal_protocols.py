"""Strict synchronous extension points for transactional domain operations."""

import inspect

from django.dispatch import Signal


class SynchronousSignal(Signal):
    """A Django signal that rejects asynchronous receivers at registration."""

    def connect(self, receiver, *args, **kwargs):
        call = getattr(receiver, "__call__", None)
        if inspect.iscoroutinefunction(receiver) or inspect.iscoroutinefunction(call):
            raise TypeError("SynchronousSignal receivers must be synchronous")
        return super().connect(receiver, *args, **kwargs)
