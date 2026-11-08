# Shared reference options

Contract version is 1.0.0. The server baseline is `577b90631b5fe78dc8c0a68950b6b265ad4815bb`.

The existing authenticated options endpoint exposes `timezones` and `currency_codes` through the common module's option provider. Timezone values are IANA identifiers. Currency values are standard alphabetic codes with names, numeric codes and minor units from the published ISO 4217 reference catalog.

Reading options leaves the database unchanged. Existing configured currency names, symbols, precision and active flags are retained. Existing saved currency codes remain available in the catalog even when they are absent from the current reference list.

Reference metadata is checked into the package with its source and publication date. Runtime reads use that packaged catalog and the installed timezone database. UI clients may localize currency names using the stable codes.

Verification covers complete reference coverage, selectable precision, legacy configured currencies, inactive flags, authentication and the existing options provider protocol.

The dispatch result is recorded in `bfg2/bfg/docs/reference-options-dispatch.json`.
