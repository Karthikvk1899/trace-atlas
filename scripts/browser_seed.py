"""Output a credential file for CI/browser tests. Never publish this output as an artifact."""

import json
import os

from atlas.cli import call, demo_evidence
from atlas.db import provision

account = provision("Browser verification")
os.environ["ATLAS_URL"] = "http://localhost:8080"
os.environ["ATLAS_TOKEN"] = account["investigator"]
good = demo_evidence(200)
call("POST", "/api/executions", good)
call("POST", "/api/executions", demo_evidence(503))
account["baseline_label"] = good["name"] + " · " + good["id"][:8]
print(json.dumps(account))
