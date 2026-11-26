"""Login, registration, and email OTP verification UI page."""

import streamlit as st

from src.auth.auth_manager import AuthManager


def render_auth_page(auth_manager: AuthManager) -> None:
    """Render the authentication gate until the user signs in with a verified email."""
    _, center_col, _ = st.columns([1, 1.6, 1])

    with center_col:
        st.markdown(
            """
            <div style="text-align:center; padding: 12px 0 8px 0;">
                <h1 style="color:#1B365D; margin-bottom:4px;">Exam Monitor</h1>
                <p style="color:#64748B; margin-top:0;">
                    AI-Based Smart Exam Cheating Detection System
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        pending_email = st.session_state.get("pending_verify_email", "")
        if pending_email:
            _render_otp_verification(auth_manager, pending_email)
            return

        tab_login, tab_register = st.tabs(["Sign In", "Create Account"])

        with tab_login:
            with st.form("login_form"):
                email = st.text_input("Email Address", placeholder="controller@habush.edu")
                password = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Sign In", type="primary", use_container_width=True)

            if submitted:
                res = auth_manager.login_with_password(email, password)
                if res.success and res.user is not None:
                    st.session_state["auth_user"] = res.user
                    st.session_state.pop("demo_otp_hint", None)
                    st.rerun()
                elif res.requires_verification:
                    st.session_state["pending_verify_email"] = res.email
                    st.session_state["demo_otp_hint"] = res.demo_otp
                    st.warning(res.message)
                    st.rerun()
                else:
                    st.error(res.message)

        with tab_register:
            with st.form("register_form"):
                full_name = st.text_input("Full Name", placeholder="Enter your full name")
                reg_email = st.text_input("Email Address", placeholder="controller@example.com")
                reg_password = st.text_input("Password (min 6 chars)", type="password")
                reg_confirm = st.text_input("Confirm Password", type="password")
                reg_submitted = st.form_submit_button(
                    "Register & Send Verification Code",
                    type="primary",
                    use_container_width=True,
                )

            if reg_submitted:
                if reg_password != reg_confirm:
                    st.error("Passwords do not match.")
                else:
                    res = auth_manager.register(full_name, reg_email, reg_password)
                    if res.success and res.requires_verification:
                        st.session_state["pending_verify_email"] = res.email
                        st.session_state["demo_otp_hint"] = res.demo_otp
                        st.success(res.message)
                        st.rerun()
                    else:
                        st.error(res.message)

        with st.expander("Email (SMTP) Configuration Info"):
            st.caption(
                "To send real verification emails to any inbox, set `SMTP_USER` and "
                "`SMTP_PASSWORD` (e.g. a Gmail App Password) in `.streamlit/secrets.toml` "
                "or environment variables. Without SMTP credentials, Demo Mode displays "
                "the 6-digit verification code on screen for testing."
            )


def _render_otp_verification(auth_manager: AuthManager, email: str) -> None:
    """Render the 6-digit OTP verification step."""
    st.subheader("Verify Your Email")
    st.info(f"Enter the 6-digit verification code sent to **{email}**.")

    demo_otp = st.session_state.get("demo_otp_hint")
    if demo_otp:
        st.warning(
            f"**Demo Mode (SMTP not configured):** Your verification code is **`{demo_otp}`**"
        )

    with st.form("otp_verify_form"):
        code = st.text_input(
            "6-Digit Verification Code",
            max_chars=6,
            placeholder="123456",
        )
        verify_btn = st.form_submit_button(
            "Verify & Continue", type="primary", use_container_width=True
        )

    if verify_btn:
        res = auth_manager.verify_otp(email, code, purpose="verify")
        if res.success and res.user is not None:
            st.session_state["auth_user"] = res.user
            st.session_state.pop("pending_verify_email", None)
            st.session_state.pop("demo_otp_hint", None)
            st.success(res.message)
            st.rerun()
        else:
            st.error(res.message)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Resend Code", use_container_width=True):
            res = auth_manager.send_verification_otp(email, purpose="verify")
            if res.success:
                st.session_state["demo_otp_hint"] = res.demo_otp
                st.success(res.message)
                st.rerun()
            else:
                st.error(res.message)
    with col2:
        if st.button("Back to Login", use_container_width=True):
            st.session_state.pop("pending_verify_email", None)
            st.session_state.pop("demo_otp_hint", None)
            st.rerun()
