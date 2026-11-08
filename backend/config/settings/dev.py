from .base import *

DEBUG = env.bool("DJANGO_DEBUG", default=True)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
# The Vite dev server proxies the API over plain http://localhost.
FMS_REFRESH_COOKIE_SECURE = env.bool("FMS_REFRESH_COOKIE_SECURE", default=False)
