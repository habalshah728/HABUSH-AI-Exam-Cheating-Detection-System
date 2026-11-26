"""Authentication and email OTP verification package."""

from src.auth.auth_manager import AuthManager, AuthResult
from src.auth.email_service import EmailConfig, EmailSendResult, EmailService

__all__ = [
    "AuthManager",
    "AuthResult",
    "EmailConfig",
    "EmailSendResult",
    "EmailService",
]
