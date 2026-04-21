from __future__ import annotations
import os


class ServerSettings:
    SERVICE_NAME = "HALbridge server_api"

    @staticmethod
    def api_token() -> str:
        return os.environ.get("HALBRIDGE_API_TOKEN", "change_me")

    @staticmethod
    def host() -> str:
        return os.environ.get("HALBRIDGE_SERVER_HOST", "127.0.0.1")

    @staticmethod
    def port() -> int:
        return int(os.environ.get("HALBRIDGE_SERVER_PORT", "5001"))
