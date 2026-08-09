"""Global test safety configuration."""

import os

# Tests must never send traces using a developer's local LangSmith credentials.
os.environ["LANGSMITH_TRACING"] = "false"
