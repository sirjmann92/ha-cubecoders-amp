"""Constants for the AMP integration."""

DOMAIN = "cubecoders"

# Optional base32 TOTP secret for AMP users that require 2FA.
CONF_TOTP_SECRET = "totp_secret"

# URL base for assets bundled with the integration (registered in __init__).
STATIC_URL_BASE = "/cubecoders_static"
