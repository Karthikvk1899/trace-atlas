"""Create local database credentials without overwriting an existing environment."""

import os
import secrets
from pathlib import Path

path = Path(".env")
try:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    print(".env already exists; kept unchanged")
else:
    with os.fdopen(fd, "w") as handle:
        handle.write("POSTGRES_PASSWORD=" + secrets.token_hex(24) + "\n")
    print("Created .env. Keep it private and out of version control.")
