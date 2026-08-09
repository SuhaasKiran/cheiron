import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "apps" / "backend" / "src"))

from cheiron_core.http_api import create_default_http_api

app = create_default_http_api()
