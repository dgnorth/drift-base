from decouple import AutoConfig
config = AutoConfig(__file__)

# this file overrides settings from config.json.
# settings here are loaded from settings.ini for local development
# or from environment.

DEBUG = config("DEBUG", default=False, cast=bool)
LOG_LEVEL = config("LOG_LEVEL", default="INFO")
LOG_FORMAT = config("LOG_FORMAT", default="json")
