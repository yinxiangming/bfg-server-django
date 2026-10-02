"""
Development settings
"""
from .settings import *

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

# Development-specific settings can be added here

# Capture development verification mail locally when using the file backend.
EMAIL_FILE_PATH = os.environ.get('EMAIL_FILE_PATH', '/private/tmp/nexus-branding-mail')

# Explicit opt-in for local HTTP tenant routing; production remains HTTPS.
BFG_LOCAL_HTTP_FRONTEND = os.environ.get("BFG_LOCAL_HTTP_FRONTEND", "false").lower() == "true"
