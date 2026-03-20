from types import SimpleNamespace

from bfg.common.services.customer_service import CustomerService


def test_deactivate_customer_sets_inactive_and_saves():
    service = CustomerService(workspace=SimpleNamespace(id=1), user=None)
    customer = SimpleNamespace(workspace_id=1, is_active=True)
    state = {"saved": False}
    customer.save = lambda: state.update({"saved": True})

    result = service.deactivate_customer(customer)
    assert result.is_active is False
    assert state["saved"] is True
