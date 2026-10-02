"""Server-only provider credential, never returned to clients."""
import os
SETTINGS = {'GOOGLE_MAPS_API_KEY': os.environ.get('GOOGLE_MAPS_API_KEY', '').strip()}
