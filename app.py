import logging
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "apps" / "backend" / "src"))

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger("cheiron.app")

app = None

try:
    from cheiron_core.http_api import create_default_http_api

    app = create_default_http_api()
    logger.info("cheiron_core.http_api: app created successfully")
except Exception:
    print("ERROR: Failed to create app via create_default_http_api()", file=sys.stderr, flush=True)
    traceback.print_exc(file=sys.stderr)
    sys.stderr.flush()
    logger.exception("Failed to create app via create_default_http_api()")
    raise
