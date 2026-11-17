import json
from pathlib import Path

from atlas.api import app
from atlas.contracts import Execution

Path("docs/openapi.json").write_text(json.dumps(app.openapi(), indent=2) + "\n")
Path("docs/execution.schema.json").write_text(json.dumps(Execution.model_json_schema(), indent=2) + "\n")
