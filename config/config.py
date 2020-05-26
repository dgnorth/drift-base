from decouple import AutoConfig
import json
config = AutoConfig(__file__)

# this file overrides settings from config.json.
# settings here are loaded from settings.ini for local development
# or from environment.

DEBUG = config("DEBUG", default=False, cast=bool)
LOG_LEVEL = config("LOG_LEVEL", default="INFO")
LOG_FORMAT = config("LOG_FORMAT", default="json")
HOST_ADDRESS = config("HOST_ADDRESS", default=None)
DOCKER_IMAGE = config("DOCKER_IMAGE", default=None)

BUILD_INFO = {}
try:
    with open(".build_info") as f:
        data = json.load(f)
        VERSION = data.get("version")
        BUILD_INFO = data
except Exception:
    pass
