"""Strict extension points for delivery state transitions."""

from bfg.core.signal_protocols import SynchronousSignal


consignment_status_update_exclusions = SynchronousSignal()


def excluded_consignment_ids(*, workspace, candidate_ids, new_state):
    """Collect validated exclusions without permitting candidate replacement."""
    if not isinstance(candidate_ids, tuple):
        raise TypeError("candidate_ids must be an immutable tuple")
    if any(type(value) not in (int, str) for value in candidate_ids):
        raise TypeError("candidate_ids must contain only integer or string IDs")
    candidate_set = set(candidate_ids)
    excluded = set()
    responses = consignment_status_update_exclusions.send(
        sender=excluded_consignment_ids,
        workspace=workspace,
        candidate_ids=candidate_ids,
        new_state=new_state,
    )
    for receiver, response in responses:
        if not isinstance(response, (tuple, list, set, frozenset)):
            raise TypeError(
                f"{receiver!r} must return a tuple, list, set, or frozenset of IDs"
            )
        for value in response:
            if type(value) not in (int, str):
                raise TypeError(f"{receiver!r} returned an invalid consignment ID")
            if value not in candidate_set:
                raise ValueError(f"{receiver!r} excluded a consignment outside the candidates")
            excluded.add(value)
    return excluded
