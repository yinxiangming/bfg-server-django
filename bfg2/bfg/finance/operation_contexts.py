"""Extension-owned context managers around finance state transitions."""

from contextlib import ExitStack, contextmanager

from bfg.core.signal_protocols import SynchronousSignal


finance_operation_contexts = SynchronousSignal()


class _NonSuppressingContext:
    def __init__(self, context):
        self.context = context

    def __enter__(self):
        return self.context.__enter__()

    def __exit__(self, exc_type, exc_value, traceback):
        self.context.__exit__(exc_type, exc_value, traceback)
        return False


def _receiver_key(receiver):
    return (
        getattr(receiver, "__module__", type(receiver).__module__),
        getattr(receiver, "__qualname__", type(receiver).__qualname__),
    )


@contextmanager
def finance_operation_context(workspace, operation):
    """Enter extension contexts in a stable order for one finance operation."""
    responses = finance_operation_contexts.send(
        sender=finance_operation_context,
        workspace=workspace,
        operation=operation,
    )
    with ExitStack() as stack:
        for receiver, context in sorted(responses, key=lambda item: _receiver_key(item[0])):
            if not hasattr(context, "__enter__") or not hasattr(context, "__exit__"):
                name = ".".join(_receiver_key(receiver))
                raise TypeError(f"{name} must return a synchronous context manager")
            stack.enter_context(_NonSuppressingContext(context))
        yield
