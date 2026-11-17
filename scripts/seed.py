"""Run inside API container. Prints demo credentials only to the invoking terminal."""

import json
import os

from atlas.cli import call, demo_evidence
from atlas.db import provision

account = provision("Demo investigation")
os.environ["ATLAS_TOKEN"] = account["investigator"]
os.environ["ATLAS_URL"] = "http://localhost:8080"
for status in (200, 503):
    call("POST", "/api/executions", demo_evidence(status))
print(json.dumps(account, indent=2))
