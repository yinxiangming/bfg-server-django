# Carrier Plugin Testing Command

Django management command for testing carrier plugins with specified configuration.

## Overview

The `plugin` command allows you to test carrier plugins (such as ParcelPort, Starshipit) with custom credentials and configurations without modifying database records.

## Usage

```bash
python manage.py plugin carrier [OPTIONS]
```

## Command Structure

```
plugin carrier --name <plugin_name> [--test] [--account <account>] [--secret <secret>] [--workspace <workspace>] [--use-existing]
```

## Arguments

### Required Arguments

- `--name <plugin_name>`: Carrier plugin name (e.g., `parcelport`, `starshipit`)
  - Required: Yes
  - Example: `--name parcelport`

### Optional Arguments

- `--test`: Use test mode (default: use production/live mode)
  - Example: `--test`

- `--account <account>`: Account/username for authentication
  - Example: `--account surlex`

- `--secret <secret>`: Secret/password for authentication
  - Example: `--secret Abcd123321`

- `--workspace <workspace_name>`: Workspace name (default: use first available workspace)
  - Example: `--workspace ATL`

- `--use-existing`: Use existing Carrier configuration from database instead of `--account/--secret`
  - Example: `--use-existing`

## Examples

### Test ParcelPort with Command Line Credentials (Production)

```bash
python manage.py plugin carrier --name parcelport --account surlex --secret Abcd123321
```

### Test ParcelPort in Test Mode

```bash
python manage.py plugin carrier --test --name parcelport --account surlex --secret Abcd123321
```

### Test Using Database Configuration

```bash
python manage.py plugin carrier --name parcelport --use-existing
```

### Test with Specific Workspace

```bash
python manage.py plugin carrier --name parcelport --account surlex --secret Abcd123321 --workspace ATL
```

### Test Other Carriers (e.g., Starshipit)

```bash
python manage.py plugin carrier --name starshipit --account api_key_value --secret subscription_key_value
```

## What the Command Tests

The command performs the following tests:

1. **Plugin Loading**: Verifies the plugin can be loaded and initialized
2. **Authentication**: Tests API authentication with provided credentials
3. **Shipping Options**: Retrieves available shipping options/quotes
4. **Consignment Creation**: Creates a test consignment using the first available shipping option
5. **Label Generation**: Retrieves and downloads the shipping label PDF

## Test Data

The command uses the following test addresses (Auckland, New Zealand):

- **Sender Address**:
  - Street: 123 Queen Street
  - City: Auckland
  - Postal Code: 1010
  - Country: NZ

- **Recipient Address**:
  - Street: 456 Ponsonby Road
  - City: Auckland
  - Postal Code: 1021
  - Country: NZ

- **Package**:
  - Weight: 1.5 kg
  - Dimensions: 20cm x 15cm x 10cm

## Output

The command provides detailed output for each test step:

```
Testing ParcelPort Carrier Plugin
Workspace: Demo Workspace
Carrier Type: parcelport
Test Mode: False
Account: surlex

Plugin loaded: ParcelPortCarrier
Display name: ParcelPort
Base URL: https://api.parcelport.co.nz

Testing authentication...
✓ Authentication successful
  Token: ***

Testing shipping options...
✓ Shipping options retrieved: 2 options
  1. Freight (ft_freight)
     Price: $3.77 NZD
     Estimated days: 1-7
  2. Courier Parcel (CPOLP)
     Price: $5.87 NZD
     Estimated days: 1-7

Testing consignment creation...
✓ Consignment created
  Tracking Number: 019197237633

Testing label retrieval...
✓ Label retrieved
  Label URL: https://ship.zappy.nz/Consignment/DownloadPDF?ConsignmentSel=...
✓ Label downloaded: 110875 bytes
  Saved to: /tmp/parcelport_labels/label_019197237633_20260112_111051.pdf

Test completed!
```

## Label Download

Labels are automatically downloaded and saved to:
```
/tmp/parcelport_labels/label_{tracking_number}_{timestamp}.pdf
```

## Configuration Mapping

The command automatically maps `--account` and `--secret` to plugin-specific fields:

- **ParcelPort**: Maps to `username` and `password`
- **Starshipit**: Maps to `api_key` and `subscription_key`
- Other plugins: Automatically detected from plugin's config schema

## Error Handling

The command provides clear error messages for common issues:

- Plugin not found: Lists available plugins
- Authentication failed: Shows API error message
- Configuration incomplete: Indicates missing required fields
- Workspace not found: Suggests creating a workspace

## Notes

- The command uses temporary carrier instances for testing (when using `--account/--secret`)
- When using `--use-existing`, it reads configuration from the database Carrier record
- Test mode uses test/sandbox API endpoints (e.g., `https://apitest.parcelport.co.nz`)
- Production mode uses live API endpoints (e.g., `https://api.parcelport.co.nz`)
- Created consignments are real and will appear in the carrier system

## Troubleshooting

### Plugin Not Found

If you see "Carrier plugin not found", check:
- Plugin is installed in `bfg/delivery/carriers/{plugin_name}/`
- Plugin class inherits from `BaseCarrierPlugin`
- Plugin has `carrier_type` attribute set

### Authentication Failed

- Verify credentials are correct
- Check if account is active
- Ensure you're using the correct environment (test vs production)

### No Shipping Options Returned

- Verify addresses are valid
- Check package dimensions are reasonable
- Ensure API endpoint is correct for the environment

## Related Files

- Plugin implementation: `bfg/delivery/carriers/{plugin_name}/plugin.py`
- Command implementation: `bfg/delivery/management/commands/plugin.py`
- Base plugin class: `bfg/delivery/carriers/base.py`
