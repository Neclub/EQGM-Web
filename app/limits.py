"""Public-safe caps for the free-tier EQGM Web service."""

from __future__ import annotations

# Upload / roster
MAX_FILES = 80
MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MB per file
MAX_TOTAL_UPLOAD_BYTES = 40 * 1024 * 1024
MAX_CHARACTERS = 20
ALLOWED_SUFFIXES = (".txt",)

# Jobs
JOB_TTL_SECONDS = 15 * 60
SESSION_TTL_SECONDS = 30 * 60
GENERATE_TIMEOUT_SECONDS = 10 * 60

# Concurrency / rate limits
GLOBAL_GENERATE_SLOTS = 1
PER_IP_GENERATE_COOLDOWN_SECONDS = 30
PER_IP_MAX_GENERATES_PER_HOUR = 20

ALLOWED_NAME_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._- "
)
