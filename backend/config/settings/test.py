import os
import tempfile

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-insecure-key-not-for-production-use-0000")
os.environ.setdefault("DATABASE_URL", "postgres://fms:fms@localhost:55432/fms")

from .base import *

DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost"]
# Fast hashing in tests only.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {"auth": "1000/min"}

STORAGES["default"]["OPTIONS"] = {"location": tempfile.mkdtemp(prefix="fms-test-files-")}
FMS_MAX_UPLOAD_MB = 1
