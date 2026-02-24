"""Authentication configuration model."""

from __future__ import annotations

import os
import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator


def _interpolate_env(value: str | None) -> str | None:
    """Replace ${VAR} with environment variable values. Leave as-is if unset."""
    if value is None:
        return None
    return re.sub(
        r"\$\{(\w+)\}",
        lambda m: os.environ.get(m.group(1), m.group(0)),
        value,
    )


class AuthConfig(BaseModel):
    """Configuration for the auth section of ergane.yaml."""

    login_url: str
    mode: Literal["auto", "manual"] = "auto"

    # CSS selectors for automated login (mode: auto)
    username_selector: str | None = None
    password_selector: str | None = None
    submit_selector: str | None = Field(
        default=None,
        description="CSS selector for the login submit button",
    )

    # Credentials (support ${ENV_VAR} interpolation)
    username: str | None = None
    password: str | None = None

    # Session validation
    check_url: str | None = None
    session_file: str = ".ergane_session.json"
    session_ttl: int = Field(default=3600, gt=0)

    # Wait condition after login
    wait_after_login: str | None = Field(
        default=None,
        description="Playwright wait: 'networkidle', 'domcontentloaded', 'load', or a CSS selector",
    )

    @model_validator(mode="after")
    def _validate_auto_mode(self) -> AuthConfig:
        if self.mode == "auto":
            if self.username is not None and self.username_selector is None:
                raise ValueError(
                    "mode='auto' with credentials requires username_selector"
                )
            if self.password is not None and self.password_selector is None:
                raise ValueError(
                    "mode='auto' with credentials requires password_selector"
                )
        return self

    @model_validator(mode="after")
    def _interpolate_credentials(self) -> AuthConfig:
        self.username = _interpolate_env(self.username)
        self.password = _interpolate_env(self.password)
        return self
