from __future__ import annotations

import importlib
import inspect
import sys
import types
from types import SimpleNamespace


def install_import_shims() -> None:
    support_models = importlib.import_module("bfg.support.models")
    if not hasattr(support_models, "Ticket"):
        support_models.Ticket = support_models.SupportTicket
    if not hasattr(support_models, "TicketMessage"):
        support_models.TicketMessage = support_models.SupportTicketMessage

    if "bfg.shop.batch_models" not in sys.modules:
        batch_models = types.ModuleType("bfg.shop.batch_models")

        class _DummyModel:
            objects = SimpleNamespace(create=lambda **kwargs: SimpleNamespace(**kwargs))

        batch_models.ProductBatch = _DummyModel
        batch_models.BatchMovement = _DummyModel
        sys.modules["bfg.shop.batch_models"] = batch_models


def assert_service_module_basic(module_name: str) -> None:
    install_import_shims()
    module = importlib.import_module(module_name)

    service_classes = []
    for _, cls in inspect.getmembers(module, inspect.isclass):
        if cls.__module__ == module.__name__ and cls.__name__.endswith("Service"):
            service_classes.append(cls)

    assert service_classes, f"No *Service class found in {module_name}"

    for service_cls in service_classes:
        kwargs = {}
        signature = inspect.signature(service_cls.__init__)

        for name, parameter in signature.parameters.items():
            if name == "self":
                continue
            if parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue
            if name == "workspace" and service_cls.__name__ == "BatchService":
                kwargs[name] = SimpleNamespace(id=1, settings={"features": {"batch_management": True}})
            elif name in {"workspace", "user"}:
                kwargs[name] = None
            elif parameter.default is inspect.Parameter.empty:
                kwargs[name] = None

        instance = service_cls(**kwargs)
        assert instance is not None

        if hasattr(instance, "execute_in_transaction"):
            assert instance.execute_in_transaction(lambda: "ok") == "ok"

        if hasattr(instance, "emit_event"):
            captured = {}
            instance.events = SimpleNamespace(
                dispatch=lambda event_name, event_data: captured.update(
                    {"event_name": event_name, "event_data": event_data}
                )
            )
            instance.emit_event("test.event", {"key": "value"})
            assert captured["event_name"] == "test.event"
            assert captured["event_data"]["data"] == {"key": "value"}
