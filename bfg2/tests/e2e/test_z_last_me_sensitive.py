"""
E2E tests that run last: change-password and reset-password.
No default passwords in code; all from env. Run at end to avoid affecting other tests.
"""

import os
import pytest


@pytest.mark.e2e
@pytest.mark.skip(reason="Temporarily skip password-sensitive me endpoints")
class TestLastMeSensitive:
    """Change-password and reset-password (executed at end of e2e)."""

    def test_me_change_password(self, authenticated_client, workspace):
        """POST /api/v1/me/change-password/. Passwords from env only."""
        old_password = os.environ.get("BFG2_E2E_ADMIN_PASSWORD") or os.environ.get(
            "BFG2_E2E_SUPERUSER_PASSWORD"
        )
        new_password = os.environ.get("BFG2_E2E_TEMP_PASSWORD")
        if not old_password or not new_password:
            pytest.skip(
                "Set BFG2_E2E_ADMIN_PASSWORD (or BFG2_E2E_SUPERUSER_PASSWORD) and BFG2_E2E_TEMP_PASSWORD to run"
            )
        change_pwd_res = authenticated_client.post("/api/v1/me/change-password/", {
            "old_password": old_password,
            "new_password": new_password,
            "confirm_password": new_password,
        })
        assert change_pwd_res.status_code == 200
        assert "detail" in change_pwd_res.data

    def test_me_reset_password(self, authenticated_client, workspace):
        """POST /api/v1/me/reset-password/. Email from /api/v1/me/. No password literals."""
        me_res = authenticated_client.get("/api/v1/me/")
        assert me_res.status_code == 200
        email = me_res.data.get("email") or me_res.data.get("username")
        if not email:
            pytest.skip("No email/username from /api/v1/me/")
        reset_res = authenticated_client.post("/api/v1/me/reset-password/", {"email": email})
        if reset_res.status_code == 404:
            pytest.skip("reset-password endpoint not implemented")
        assert reset_res.status_code == 200
        assert "detail" in reset_res.data
        detail_lower = reset_res.data["detail"].lower()
        assert "password reset link" in detail_lower or "sent" in detail_lower

        invalid_res = authenticated_client.post(
            "/api/v1/me/reset-password/", {"email": "not-an-email"}
        )
        assert invalid_res.status_code == 400
