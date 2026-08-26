"""
Rate limiting configuration using slowapi.
Protects critical endpoints (auth, OAuth) from brute force and DoS attacks.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

# Rate limit definitions (key: display name, value: limit expression)
# Format: "N/period" where period is s/m/h/d
LIMITS = {
    "auth_login": "5/15 minutes",           # 5 attempts per 15 minutes per IP
    "auth_register": "3/1 hour",            # 3 registrations per hour per IP
    "facebook_callback": "10/15 minutes",   # 10 OAuth callbacks per 15 minutes per IP
    "reports_generate": "20/1 hour",        # 20 report generations per hour per IP
}
