"""Unit tests for AuthManager registration, OTP verification, and login."""

from pathlib import Path

from src.auth.auth_manager import AuthManager
from src.auth.email_service import EmailConfig, EmailService
from src.storage.database import DatabaseManager


def test_register_verify_otp_and_login(tmp_path: Path):
    db = DatabaseManager(tmp_path / "auth_test.db")
    # Unconfigured SMTP triggers Demo Mode and returns demo_otp
    email_svc = EmailService(EmailConfig(smtp_user="", smtp_password=""))
    auth = AuthManager(db, email_svc)

    reg_res = auth.register("Malik Hassan", "hassan@bahria.edu.pk", "secret123")
    assert reg_res.success is True
    assert reg_res.requires_verification is True
    assert reg_res.demo_otp is not None
    assert len(reg_res.demo_otp) == 6

    # Login before verification must require verification
    pre_login = auth.login_with_password("hassan@bahria.edu.pk", "secret123")
    assert pre_login.success is False
    assert pre_login.requires_verification is True
    latest_otp = pre_login.demo_otp
    assert latest_otp is not None

    # Wrong OTP fails
    bad_verify = auth.verify_otp("hassan@bahria.edu.pk", "000000")
    assert bad_verify.success is False

    # Correct OTP verifies account
    good_verify = auth.verify_otp("hassan@bahria.edu.pk", latest_otp)
    assert good_verify.success is True
    assert good_verify.user is not None
    assert good_verify.user["is_verified"] == 1

    # Verified user can now sign in with password
    login_res = auth.login_with_password("hassan@bahria.edu.pk", "secret123")
    assert login_res.success is True
    assert login_res.user["email"] == "hassan@bahria.edu.pk"


def test_admin_seed_and_password_change_persists(tmp_path: Path):
    db = DatabaseManager(tmp_path / "admin_test.db")
    auth = AuthManager(db, EmailService(EmailConfig(smtp_user="", smtp_password="")))

    auth.ensure_admin_account("admin@example.com", "TestAdmin#2026", campus="HQ")
    login1 = auth.login_with_password("admin@example.com", "TestAdmin#2026")
    assert login1.success is True
    assert login1.user is not None and login1.user["is_admin"] == 1

    # Regular users list hides privileged admin account
    auth.register("User One", "u1@example.com", "pass1234", campus="Main Campus")
    users = db.get_all_users(include_admins=False)
    assert len(users) == 1
    assert users[0]["email"] == "u1@example.com"
    assert users[0]["campus"] == "Main Campus"

    # Changing password persists across subsequent ensure_admin_account restarts
    chg = auth.change_password("admin@example.com", "TestAdmin#2026", "NewPass@99")
    assert chg.success is True
    auth.ensure_admin_account("admin@example.com", "TestAdmin#2026", campus="HQ")
    assert auth.login_with_password("admin@example.com", "TestAdmin#2026").success is False
    assert auth.login_with_password("admin@example.com", "NewPass@99").success is True


def test_smtp_network_blocked_falls_back_to_demo_mode(tmp_path: Path):
    db = DatabaseManager(tmp_path / "fallback_test.db")
    cfg = EmailConfig(
        smtp_host="127.0.0.1",
        smtp_port=59999,  # Closed port simulates cloud SMTP block
        smtp_user="sender@gmail.com",
        smtp_password="dummy-app-password",
    )
    auth = AuthManager(db, EmailService(cfg))
    res = auth.register("Test User", "user@example.com", "pass1234", campus="Main Campus")
    assert res.success is True
    assert res.requires_verification is True
    assert res.demo_otp is not None and len(res.demo_otp) == 6
    verified = auth.verify_otp("user@example.com", res.demo_otp)
    assert verified.success is True
