# -*- coding: utf-8 -*-
"""
Marking the writes that are still allowed while a workspace is read only.

A workspace whose base plan has lapsed can be put into read only — see
``bfg.platform.services.read_only`` for when, and
``bfg.platform.middleware.ReadOnlyWorkspaceMiddleware`` for the refusal itself.
Everything unsafe is refused there unless the view handling the request carries
the mark this module applies.

The mark is an attribute read off the resolved view, not a list of URL prefixes
kept somewhere else. A route that is renamed or remounted keeps its exemption
without anyone remembering to update a second file, and a view added next to an
exempt one does not quietly inherit it. It also means a reader of the view can
see that it is exempt, which a table of paths in another module does not give
them.

It lives in ``bfg.core`` — the module every other one already depends on — so
that marking a view does not make its app import the platform app.

Marking a **class** exempts every method on it, subclasses included, which is
why the narrower marks are the ones to reach for first:

    class OrderViewSet(ModelViewSet):

        @exempt_from_read_only
        @action(detail=True, methods=["post"])
        def ship(self, request, pk=None):
            ...

    # Whole view. Only where every write it can serve is allowed.
    @exempt_from_read_only
    class PlatformBillingViewSet(ViewSet):
        ...

For a plain function view the mark goes **outside** ``@api_view``, because
``@api_view`` builds a new view out of the function it is given::

    @exempt_from_read_only
    @api_view(["POST"])
    def pay_invoice(request):
        ...

(The other order is understood too, but it reads as though the function were
being marked rather than the view, so prefer the one above.)
"""

from __future__ import annotations

import logging

# The attributes the mark writes. Spelled once so the decorator and the reader
# cannot drift apart, and so a view can be inspected for them in a test.
ATTRIBUTE = "read_only_exempt"
CONDITION_ATTRIBUTE = "read_only_exempt_when"

logger = logging.getLogger(__name__)


def exempt_from_read_only(target=None, *, when=None):
    """Mark ``target`` as still allowed while its workspace is read only.

    Takes a view class, a viewset method (an ``@action``, or any of the standard
    ones), or a function view, and returns it unchanged apart from the mark, so
    it composes with the other view decorators.

    ``when`` narrows the exemption to the requests that satisfy a predicate
    ``(request, view_kwargs) -> bool``, for a view that may be written to for
    some objects and not others — fulfilling an order that is already paid, say,
    while an unpaid one stays untouchable. It is called before the view runs, so
    it can only use what the URL and the headers say; anything that would need
    the request body is not a question to ask here, because reading the body at
    this point takes it away from the view that is about to parse it.

    A predicate that raises is treated as *allowing* the request, on the same
    reasoning as the rest of read-only mode: a failure to decide must not close
    a shop that is trading. It is logged at ERROR.

    Marking something does not decide anything on its own: the middleware asks
    whether a *write* is exempt, and reads are never refused in the first place.
    """

    def mark(obj):
        setattr(obj, ATTRIBUTE, True)
        if when is not None:
            setattr(obj, CONDITION_ATTRIBUTE, when)
        return obj

    # Called with arguments (``@exempt_from_read_only(when=...)``) rather than
    # applied directly, so hand back the decorator itself.
    return mark if target is None else mark(target)


def _marked(obj) -> bool:
    return bool(getattr(obj, ATTRIBUTE, False))


def _condition_holds(obj, request, view_kwargs) -> bool:
    """Whether ``obj``'s exemption applies to this request. True when unconditional."""
    predicate = getattr(obj, CONDITION_ATTRIBUTE, None)
    if predicate is None:
        return True
    try:
        return bool(predicate(request, view_kwargs or {}))
    except Exception:
        logger.exception(
            "A read-only exemption condition on %r could not be evaluated; allowing the request",
            getattr(obj, "__qualname__", obj),
        )
        return True


def _action_name(view_func, method: str):
    """Which viewset method will handle ``method``, when the view is a viewset.

    DRF's router records the mapping on the view function it builds
    (``ViewSetMixin.as_view`` sets ``actions``), so the handler is known from the
    resolved URL alone — before the view is instantiated, which is the only point
    a middleware gets. ``None`` for anything that is not a viewset.
    """
    actions = getattr(view_func, "actions", None)
    if not actions:
        return None
    return actions.get(method.lower())


def is_exempt(view_func, request, view_kwargs=None) -> bool:
    """Whether ``view_func`` is marked as allowed for this request.

    Four places are looked at, narrowest first, and the first mark found is the
    one whose ``when`` condition — if it has one — decides: the viewset method
    that will actually handle this HTTP method, the function a marked
    ``@api_view`` was built from, the view function itself (a marked function
    view), and the view class (a mark covering everything on it). Narrowest
    first so that a mark on one action still says something on a class that
    happens to be marked as a whole.

    Cheap enough to sit on the write path: attribute lookups and one dictionary
    lookup, no import and no query, unless a mark carries a condition that asks
    for one.
    """
    candidates = []
    view_cls = getattr(view_func, "cls", None)
    if view_cls is not None:
        action = _action_name(view_func, request.method)
        if action is not None:
            candidates.append(getattr(view_cls, action, None))
        # ``@api_view`` keeps the function it wrapped as ``handler`` on the class
        # it generates, so a mark applied under the decorator is still findable.
        candidates.append(getattr(view_cls, "handler", None))
    candidates.append(view_func)
    if view_cls is not None:
        candidates.append(view_cls)

    for candidate in candidates:
        if candidate is not None and _marked(candidate):
            return _condition_holds(candidate, request, view_kwargs)
    return False
