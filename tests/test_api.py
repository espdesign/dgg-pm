import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from src.adapters.api.app import api_app, require_metrics_permission
from src.config import settings


@pytest.mark.parametrize(
    ("token", "credentials", "expect_raise"),
    [
        # No token configured -> open endpoint, no auth needed
        ("", None, False),
        ("", HTTPAuthorizationCredentials(scheme="Bearer", credentials="anything"), False),
        # Token configured -> missing/invalid credentials rejected
        ("s3cr3t", None, True),
        ("s3cr3t", HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong"), True),
        # Token configured -> correct token accepted
        ("s3cr3t", HTTPAuthorizationCredentials(scheme="Bearer", credentials="s3cr3t"), False),
    ],
)
def test_metrics_permission(token, credentials, expect_raise):
    original = settings.API_METRICS_TOKEN
    settings.API_METRICS_TOKEN = token
    try:
        if expect_raise:
            with pytest.raises(HTTPException) as exc_info:
                require_metrics_permission(credentials)
            assert exc_info.value.status_code == 401
        else:
            require_metrics_permission(credentials)  # should not raise
    finally:
        settings.API_METRICS_TOKEN = original


def test_metrics_route_is_guarded():
    metrics_route = next(r for r in api_app.routes if getattr(r, "path", None) == "/metrics")
    guard_names = {d.dependency.__name__ for d in metrics_route.dependencies}
    assert "require_metrics_permission" in guard_names

    health_route = next(r for r in api_app.routes if getattr(r, "path", None) == "/healthz")
    assert not health_route.dependencies
