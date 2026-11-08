"""Common option provider discovered by the shared authenticated endpoint."""
from .reference_data import currency_options, timezone_options


def get_options(workspace):
    return {'currency_codes': currency_options(), 'timezones': timezone_options()}
