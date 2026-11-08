# Staff-scoped address country overrides v1

Contract version `1.0.0`, extension ID `geo`.
Server baseline `4969c4b5351eea598fc0c9cf96bcd6faeab15665`.
Dispatch record `extensions/geo/server/docs/country-overrides-dispatch.json`.

The existing suggestion, resolution and reverse-geocoding resources accept an
optional `country_code` query parameter. It is normalized to uppercase and must
contain two ASCII letters. Omission retains the workspace's configured market.
An explicit value equal to that market preserves the existing public contract.

Selecting a different country requires an authenticated active user with an
active staff membership and active role in the resolved workspace. Customers,
anonymous callers and staff from another workspace cannot widen the market.
The override affects one request and never modifies shared workspace settings.

Activation, configured credentials, usage caps, throttles, session billing and
result-country validation remain in effect. The configuration resource retains
its existing response. Provider cache keys include language and country, so a
result chosen for one market does not suppress another market's lookup.

The host owns this generic capability. No application pricing or dispatch
policy is introduced. Tests cover default behavior, matching-country calls,
authenticated overrides, IDOR, inactive membership, caps, provider requests and
cache separation. Provider responses in automated tests are synthetic.
