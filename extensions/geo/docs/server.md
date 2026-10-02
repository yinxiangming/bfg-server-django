# Address lookup (`apps.geo`)

Server-side Google Maps for address entry: what a shopper types becomes a short
list of real addresses, and a GPS fix becomes an address name they recognise.

Both run here rather than in the client because the WeChat mini-program cannot
load Google's JavaScript SDK, and a key shipped inside a bundle — a mini-program's
or a web page's — is a key anyone can extract and spend. Going through the server
is also the only way the workspace can be billed for what it uses, which is why
the web storefront calls these endpoints too rather than Google directly.

## Endpoints

All four are mounted at `/api/v1/geo/`.

| | |
| --- | --- |
| `GET address/config/` | `{enabled, country_code, language, provider}` — ask before offering the feature |
| `GET address/suggest/?q=&session=` | typeahead; returns `place_id` + display text |
| `GET address/resolve/?place_id=&session=` | a suggestion → address form fields |
| `GET address/reverse/?lat=&lng=` | a GPS fix → address form fields |

`resolve` and `reverse` return the same shape, so a client fills its form from one
code path:

```json
{
  "place_id": "ChIJ…",
  "display_name": "12 Queen Street",
  "formatted_address": "12 Queen Street, Auckland 1010, New Zealand",
  "address_line1": "12 Queen Street",
  "address_line2": "",
  "district": "Grey Lynn",
  "city": "Auckland",
  "state": "AUK",
  "postal_code": "1010",
  "country": "NZ",
  "latitude": -36.8485,
  "longitude": 174.7633
}
```

`session` is a Google autocomplete session token: pass the same value across the
keystrokes of one address and into the `resolve` that follows, and Google bills the
lot as one session instead of one charge per character.

## Who may call them

Anyone — **no sign-in required**. Checkout is where addresses get typed, and a
shopper at checkout usually has no account yet; requiring one would only send the
storefront back to calling Google from the browser, with a key in the page and no
way to bill the workspace for what it spends.

What every call does need is a workspace. `WorkspaceMiddleware` takes it from the
request's host or its `X-Workspace-ID` header, and a request that resolves to
nothing is refused with `400` and `{"code": "workspace_required"}` rather than
being served out of some default tenant's budget.

So, plainly: **anyone who knows a shop's storefront hostname can spend that shop's
address-lookup allowance.** Sign-in never prevented that — an account at a
storefront is free to open. Two gates bound it instead, and they do different jobs:

- the **throttles** bound the rate, per caller and per shop. They stop a crawler
  and a client that forgot to debounce. They are a speed bump, not a security
  boundary: behind a proxy an IP address is whatever the forwarded header says.
- the **monthly usage cap** bounds the bill. It is the operator's own number, and
  past it every call is refused with `402`, guest and signed-in alike.

A shop that wants none of this switches the extension off, and all four endpoints
go back to answering `404`.

## Turning it on

Two things, both required.

**Per workspace**, in Admin → Settings → General → Plugins, or directly in
`Settings.custom_settings`:

```json
{"plugins": {"address_lookup": {"enabled": true, "country_code": "NZ"}}}
```

`country_code` is ISO 3166-1 alpha-2 and defaults to the workspace's own market
(`Settings.country`). `language` defaults to the workspace's default language.

**Per server**, `GOOGLE_MAPS_API_KEY` in the environment. The key is deliberately
not a workspace setting: it is a billed credential, and `custom_settings` is
returned whole to anyone who can read the admin settings endpoint.

Give each environment its own key, restricted to the Places API (New) and the
Geocoding API and to that environment's egress address, so a leak from one cannot
spend the other's budget:

```bash
gcloud services api-keys create --project=<project> \
  --display-name="<env>-maps" \
  --api-target=service=places.googleapis.com \
  --api-target=service=geocoding-backend.googleapis.com \
  --allowed-ips=<egress>
```

**Check the egress address over the stack the server actually uses.** Both Google
endpoints publish AAAA records, so on a dual-stack host `requests` connects over
IPv6 and Google sees the v6 address — an IPv4-only allow-list then rejects every
call with `REQUEST_DENIED`, naming an address that appears nowhere in the host's
configuration. `curl https://api.ipify.org` will not show it either: ipify's plain
hostname is IPv4-only, so it reports the v4 address the API never sees. Use
`api64.ipify.org`, or read the address out of Google's own error message. On AWS
the fix is to allow the subnet's IPv6 CIDR (`ip -6 route`, or the EC2 metadata key
`subnet-ipv6-cidr-blocks`) alongside the elastic IP.

A workspace with `enabled: true` and no server key reports `enabled: false` from
`address/config/` — configured, but nothing to spend against.

## Country restriction

Applied twice, because Google only honours it once. Autocomplete takes
`includedRegionCodes` and obeys it. Reverse geocoding has no equivalent —
`components=country:` is ignored on a `latlng` request — so results are filtered
here against the country component, walking Google's most-specific-first ladder and
taking the first in-market hit. A fix just over a border returns 404 rather than an
address that would fail at checkout.

## Cost

- Autocomplete is never cached: it is per-keystroke and session-billed.
- Place details are cached for 7 days, keyed on place id and language.
- Reverse geocodes are cached for 24 hours, keyed on coordinates rounded to ~1 m —
  finer than that and GPS jitter turns a stationary phone into a second bill.

### Rates

Four limits, each keyed on the workspace as well as the caller so that one shop's
traffic can never use up another's. Guests are held to the tighter pair:

| | default | setting / env var |
| --- | --- | --- |
| `suggest`, guest | 30/min per IP | `GEO_GUEST_TYPEAHEAD_RATE` |
| `suggest`, signed in | 120/min per user | `GEO_TYPEAHEAD_RATE` |
| `resolve` + `reverse`, guest | 10/min per IP | `GEO_GUEST_LOOKUP_RATE` |
| `resolve` + `reverse`, signed in | 60/min per user | `GEO_LOOKUP_RATE` |

The guest numbers come from what one address costs: a client starts asking at
about the third character and debounces between, so a real address is six to
twelve `suggest` calls and the `resolve` that ends it is one more. A whole
checkout — delivery address, sometimes a billing address, plus a field retyped —
is roughly twenty-five suggests and three or four lookups, spread over the
minutes it takes to read a form. The limits are all of that inside a single
minute. Set either source (the settings module wins); an unparseable value is
logged and ignored rather than turning every lookup into a 500.

`address/config/` has no throttle of its own — it spends nothing at Google.

## What the workspace is billed

Three meters, declared in `extension.py` and priced in `MeterPrice`:
`maps.autocomplete`, `maps.place_details`, `maps.geocode`. Every endpoint asks
`metering.allowed` before it spends anything and records what it spent afterwards,
so nothing is billed that was not delivered.

Autocomplete follows Google's session pricing instead of being metered per
request. While a session is open its requests are only *counted*, in this app's own
`geo_autocompletesession` table:

- the `resolve` that ends a session is metered as one `maps.place_details`, and the
  counted requests are dropped unbilled — Google charges for the details call
  rather than for the typing that led to it;
- a session nobody has touched for 30 minutes was abandoned, so its requests are
  metered as `maps.autocomplete` and the row is dropped. That settlement runs off
  the back of the next request from the same workspace, up to 50 sessions at a
  time, because no environment runs Celery beat;
- a `suggest` with no `session` token gets no session pricing at Google either, so
  it is metered on the spot.

A workspace that has used up its monthly points is refused **before** the call is
made, with `402` and `{"detail": …, "code": "usage_cap_reached"}` — the code a
client shows its "you have reached this month's limit" message on.

Three things worth knowing when reading a bill:

- **A `resolve` carrying a `session` token never comes from the cache.** That call
  is what ends the session at Google; served from the cache it would never happen,
  Google would price the session as abandoned and charge for every keystroke in
  it, and we would have billed one place details and forgiven the typing. Session
  lookups always go to Google; the answer is still cached for token-less callers.
- A cached `reverse` — or a token-less `resolve` — is metered like any other. The
  cache saves the operator money at Google; it does not make the lookup free for
  the workspace. Billing only the misses would make a workspace's bill depend on
  what other workspaces had just looked up, since the cache is keyed on place and
  language rather than on tenant.
- A meter with no `MeterPrice` row records nothing: the usage is skipped and the
  platform logs it. Price all three meters before relying on the cap.

Settlement rides on live traffic, so a workspace that stops making lookups
altogether leaves its last abandoned sessions unsettled until lookups resume — a
handful of rows and a few cents. A deployment that grows a scheduler should give
it a job that calls `billing.settle_abandoned`.

## Tests

```bash
cd src/server && source .venv/bin/activate && python manage.py test apps.geo
```

Every Google call is stubbed; the tests pin our side of the contract, not Google's.
