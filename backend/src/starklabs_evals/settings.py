from __future__ import annotations

import ipaddress
import secrets
from dataclasses import dataclass, field

LOCAL_CORS_ORIGINS = (
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:8765",
    "http://localhost:8765",
)


def is_loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class AppSettings:
    db_path: str
    bind_host: str = "127.0.0.1"
    allow_non_loopback: bool = False
    session_token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    cors_origins: tuple[str, ...] = LOCAL_CORS_ORIGINS
    max_pack_bytes: int = 64 * 1024

    def validate(self) -> None:
        if not self.allow_non_loopback and not is_loopback_host(self.bind_host):
            msg = "Refusing non-loopback bind without explicit dev override"
            raise ValueError(msg)
        if "*" in self.cors_origins:
            msg = "Wildcard CORS origins are not allowed"
            raise ValueError(msg)
