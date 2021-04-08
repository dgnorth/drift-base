from flask import current_app

DEFAULT_CLIENT_HEARTBEAT_PERIOD = 30
DEFAULT_CLIENT_HEARTBEAT_TIMEOUT_SECONDS = 300

DEFAULT_SERVER_HEARTBEAT_PERIOD = 30
DEFAULT_SERVER_HEARTBEAT_TIMEOUT_SECONDS = 300


def get_client_heartbeat_config():
    heartbeat_period = current_app.config.get("heartbeat_period", DEFAULT_CLIENT_HEARTBEAT_PERIOD)
    heartbeat_timeout = current_app.config.get("heartbeat_timeout", DEFAULT_CLIENT_HEARTBEAT_TIMEOUT_SECONDS)
    return heartbeat_period, heartbeat_timeout


def get_server_heartbeat_config():
    heartbeat_period = current_app.config.get("server_heartbeat_period", DEFAULT_SERVER_HEARTBEAT_PERIOD)
    heartbeat_timeout = current_app.config.get("server_heartbeat_timeout", DEFAULT_SERVER_HEARTBEAT_TIMEOUT_SECONDS)
    return heartbeat_period, heartbeat_timeout
