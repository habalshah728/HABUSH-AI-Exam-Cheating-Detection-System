"""Email delivery service (HTTPS APIs + SMTP) with safe Demo Mode fallback."""

from dataclasses import dataclass
from email.message import EmailMessage
from html import escape
import json
import os
import smtplib
import ssl
from typing import Optional
import urllib.request

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class EmailConfig:
    """Email configuration loaded from environment variables or Streamlit secrets."""

    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    from_email: str = ""
    brevo_api_key: str = ""
    resend_api_key: str = ""
    email_webhook_url: str = ""
    strict_mode: bool = False

    @property
    def is_configured(self) -> bool:
        return bool(
            self.brevo_api_key
            or self.resend_api_key
            or self.email_webhook_url
            or (self.smtp_host and self.smtp_user and self.smtp_password)
        )


@dataclass(frozen=True)
class EmailSendResult:
    """Outcome of attempting to send an OTP verification email."""

    success: bool
    sent_via_smtp: bool
    message: str
    demo_code: Optional[str] = None


def load_email_config() -> EmailConfig:
    """Load HTTPS API / SMTP settings from environment variables or Streamlit secrets."""
    env_host = os.getenv("SMTP_HOST", "")
    env_port = os.getenv("SMTP_PORT", "")
    env_user = os.getenv("SMTP_USER", "")
    env_pass = os.getenv("SMTP_PASSWORD", "")
    env_from = os.getenv("SMTP_FROM", "")
    env_brevo = os.getenv("BREVO_API_KEY", "")
    env_resend = os.getenv("RESEND_API_KEY", "")
    env_webhook = os.getenv("EMAIL_WEBHOOK_URL", "")
    strict = os.getenv("EMAIL_STRICT_MODE", "").strip().lower() in ("1", "true", "yes")

    if not (env_user and env_pass) and not (env_brevo or env_resend or env_webhook):
        try:
            import streamlit as st

            secrets = st.secrets
            env_host = env_host or str(secrets.get("SMTP_HOST", "smtp.gmail.com"))
            env_port = env_port or str(secrets.get("SMTP_PORT", "587"))
            env_user = env_user or str(secrets.get("SMTP_USER", ""))
            env_pass = env_pass or str(secrets.get("SMTP_PASSWORD", ""))
            env_from = env_from or str(secrets.get("SMTP_FROM", ""))
            env_brevo = env_brevo or str(secrets.get("BREVO_API_KEY", ""))
            env_resend = env_resend or str(secrets.get("RESEND_API_KEY", ""))
            env_webhook = env_webhook or str(secrets.get("EMAIL_WEBHOOK_URL", ""))
        except Exception:
            pass

    return EmailConfig(
        smtp_host=env_host or "smtp.gmail.com",
        smtp_port=int(env_port) if str(env_port).isdigit() else 587,
        smtp_user=env_user.strip(),
        smtp_password=env_pass.strip(),
        from_email=(env_from or env_user).strip(),
        brevo_api_key=env_brevo.strip(),
        resend_api_key=env_resend.strip(),
        email_webhook_url=env_webhook.strip(),
        strict_mode=strict,
    )


class EmailService:
    """Sends 6-digit OTP emails via HTTPS Email APIs or SMTP with Demo Mode fallback."""

    def __init__(self, config: Optional[EmailConfig] = None) -> None:
        self._config = config or load_email_config()

    @property
    def is_smtp_configured(self) -> bool:
        return self._config.is_configured

    def _build_content(
        self, full_name: str, code: str, purpose: str
    ) -> tuple[str, str, str]:
        action_text = (
            "verify your Exam Monitor account"
            if purpose == "verify"
            else "sign in to Exam Monitor"
        )
        subject = f"HABUSH CMS Verification Code: {code}"
        text_body = (
            f"Hello {full_name},\n\n"
            f"Your 6-digit verification code to {action_text} is:\n\n"
            f"    {code}\n\n"
            f"This code expires in 10 minutes. If you did not request this, "
            f"please ignore this email.\n\n"
            f"— HABUSH CMS AI Exam Cheating Detection System"
        )
        html_body = f"""
        <div style="font-family:Segoe UI,Arial,sans-serif;max-width:480px;margin:auto;padding:24px;border:1px solid #e2e8f0;border-radius:10px;">
            <h2 style="color:#1b365d;margin-top:0;">HABUSH CMS Verification</h2>
            <p>Hello <strong>{escape(full_name)}</strong>,</p>
            <p>Use the following 6-digit code to {action_text}:</p>
            <div style="background:#f4f7fa;border:1px dashed #1b365d;border-radius:8px;padding:16px;text-align:center;font-size:28px;font-weight:bold;letter-spacing:6px;color:#1b365d;margin:16px 0;">
                {escape(code)}
            </div>
            <p style="color:#64748b;font-size:13px;">This code expires in 10 minutes.</p>
        </div>
        """
        return subject, text_body, html_body

    @staticmethod
    def _post_json(url: str, payload: dict, headers: dict[str, str]) -> None:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"HTTP {resp.status}")

    def _send_via_https(
        self, recipient_email: str, subject: str, text_body: str, html_body: str, code: str, full_name: str
    ) -> Optional[EmailSendResult]:
        sender = self._config.from_email or self._config.smtp_user or "noreply@habush.local"

        if self._config.email_webhook_url:
            self._post_json(
                self._config.email_webhook_url,
                {
                    "to": recipient_email,
                    "subject": subject,
                    "text": text_body,
                    "html": html_body,
                    "code": code,
                    "full_name": full_name,
                },
                {},
            )
            logger.info("Sent OTP email via HTTPS webhook to %s", recipient_email)
            return EmailSendResult(
                True, True, f"Verification code sent to {recipient_email}."
            )

        if self._config.brevo_api_key:
            self._post_json(
                "https://api.brevo.com/v3/smtp/email",
                {
                    "sender": {"name": "HABUSH CMS", "email": sender},
                    "to": [{"email": recipient_email, "name": full_name}],
                    "subject": subject,
                    "htmlContent": html_body,
                    "textContent": text_body,
                },
                {"api-key": self._config.brevo_api_key, "accept": "application/json"},
            )
            logger.info("Sent OTP email via Brevo HTTPS API to %s", recipient_email)
            return EmailSendResult(
                True, True, f"Verification code sent to {recipient_email}."
            )

        if self._config.resend_api_key:
            self._post_json(
                "https://api.resend.com/emails",
                {
                    "from": self._config.from_email or "HABUSH CMS <onboarding@resend.dev>",
                    "to": [recipient_email],
                    "subject": subject,
                    "html": html_body,
                    "text": text_body,
                },
                {"Authorization": f"Bearer {self._config.resend_api_key}"},
            )
            logger.info("Sent OTP email via Resend HTTPS API to %s", recipient_email)
            return EmailSendResult(
                True, True, f"Verification code sent to {recipient_email}."
            )

        return None

    def send_otp_email(
        self, recipient_email: str, full_name: str, code: str, purpose: str = "verify"
    ) -> EmailSendResult:
        """Send a 6-digit verification code via HTTPS API or SMTP with Demo Mode fallback."""
        if not self._config.is_configured:
            logger.info(
                "Email delivery not configured; generated demo OTP for %s (%s).",
                recipient_email,
                purpose,
            )
            return EmailSendResult(
                success=True,
                sent_via_smtp=False,
                message=(
                    "Email delivery is not configured yet. "
                    "Use the verification code shown below (Demo Mode)."
                ),
                demo_code=code,
            )

        subject, text_body, html_body = self._build_content(full_name, code, purpose)

        # 1) Prefer HTTPS (port 443) delivery when configured (works on Railway/cloud hosts).
        try:
            https_res = self._send_via_https(
                recipient_email, subject, text_body, html_body, code, full_name
            )
            if https_res is not None:
                return https_res
        except Exception as exc:
            logger.error("HTTPS email delivery failed for %s: %s", recipient_email, exc)
            if not (self._config.smtp_user and self._config.smtp_password):
                if self._config.strict_mode:
                    return EmailSendResult(False, False, f"Failed to send email: {exc}")
                return EmailSendResult(
                    True,
                    False,
                    "Cloud email service temporarily unavailable. Use the verification code below (Demo Mode).",
                    demo_code=code,
                )

        # 2) Fall back to direct SMTP (works locally and on unrestricted networks).
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self._config.from_email or self._config.smtp_user
        msg["To"] = recipient_email
        msg.set_content(text_body)
        msg.add_alternative(html_body, subtype="html")

        try:
            context = ssl.create_default_context()
            if self._config.smtp_port == 465:
                with smtplib.SMTP_SSL(
                    self._config.smtp_host,
                    self._config.smtp_port,
                    context=context,
                    timeout=12,
                ) as server:
                    server.login(self._config.smtp_user, self._config.smtp_password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(
                    self._config.smtp_host, self._config.smtp_port, timeout=12
                ) as server:
                    server.ehlo()
                    server.starttls(context=context)
                    server.ehlo()
                    server.login(self._config.smtp_user, self._config.smtp_password)
                    server.send_message(msg)

            logger.info("Sent OTP email via SMTP to %s", recipient_email)
            return EmailSendResult(
                success=True,
                sent_via_smtp=True,
                message=f"Verification code sent to {recipient_email}.",
                demo_code=None,
            )
        except OSError as exc:
            logger.warning("SMTP network unreachable/blocked for %s: %s", recipient_email, exc)
            if self._config.strict_mode:
                return EmailSendResult(
                    False, False, f"Failed to send email via SMTP: {exc}"
                )
            return EmailSendResult(
                success=True,
                sent_via_smtp=False,
                message=(
                    "Outbound SMTP port is blocked on this cloud host. "
                    "Use the verification code shown below (Demo Mode) or configure BREVO_API_KEY / EMAIL_WEBHOOK_URL."
                ),
                demo_code=code,
            )
        except Exception as exc:
            logger.error("SMTP delivery failed for %s: %s", recipient_email, exc)
            if self._config.strict_mode:
                return EmailSendResult(
                    False, False, f"Failed to send email via SMTP: {exc}"
                )
            return EmailSendResult(
                success=True,
                sent_via_smtp=False,
                message=(
                    f"SMTP email failed ({exc}). Use the verification code shown below (Demo Mode)."
                ),
                demo_code=code,
            )
