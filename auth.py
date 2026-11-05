
"""AquaSpatial — Username and password authentication.

For sensitive client data, use managed identity and server-side
access controls in addition to this application login.
"""

import base64
from pathlib import Path
import hashlib
import hmac
import re
import time

import streamlit as st


ITERATIONS = 600_000


def _verify_password(password: str, encoded: str) -> bool:
    """Verify pbkdf2_sha256$iterations$salt_hex$digest_hex."""
    try:
        algorithm, iterations_text, salt_hex, expected_hex = encoded.split("$", 3)

        if algorithm != "pbkdf2_sha256":
            return False

        iterations = int(iterations_text)

        if not (100_000 <= iterations <= 5_000_000):
            return False

        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(expected_hex)

        if len(salt) < 16 or len(expected) != 32:
            return False

        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations
        )

        return hmac.compare_digest(candidate, expected)

    except (ValueError, TypeError, AttributeError):
        return False


def require_login() -> None:
    """Block dashboard access until authentication succeeds."""

    # ----------------------------------------
    # 1. ALREADY AUTHENTICATED
    # ----------------------------------------

    if st.session_state.get("wq_authenticated", False):

        with st.sidebar:
            username = st.session_state.get("wq_username", "")

            st.caption(f"Signed in: {username}")

            if st.button("Sign out", key="wq_signout"):
                st.session_state.pop("wq_authenticated", None)
                st.session_state.pop("wq_username", None)
                st.rerun()

        return

    # ----------------------------------------
    # 2. AQUA OCEAN LOGIN THEME
    # ----------------------------------------

    st.markdown(
        """
        <style>
        .stApp {
            background: linear-gradient(
                150deg,
                #E8F7FB,
                #FFFFFF
            );
        }

        h1 {
            color: #073B5D !important;
            font-weight: 750 !important;
        }

        h2, h3 {
            color: #087EAC !important;
        }

        [data-testid="stSidebar"] {
            display: none;
        }

        div.stButton > button[kind="primary"],
        div.stFormSubmitButton > button[kind="primary"] {
            background: #087EAC !important;
            color: #FFFFFF !important;
            border-radius: 9px !important;
        }

        div.stForm {
            border: 1px solid #B7E2EB;
            border-radius: 14px;
            background: rgba(255,255,255,0.85);
            padding: 16px;
        }
        .pm-login-brand {
            position: fixed;
            left: 22px;
            bottom: 19px;
            z-index: 3;
            width: 90px;
            opacity: .58;
            pointer-events: none;
        }
        .pm-login-brand img { display: block; width: 100%; height: auto; }
        @media (max-width: 720px) {
            .pm-login-brand { width: 58px; left: 9px; bottom: 8px; opacity: .4; }
        }
        div[data-testid="stFormSubmitButton"] button[kind="primary"] {
            background: #087EAC !important;
            border: 1px solid #087EAC !important;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    # Transparent PM corner branding, available locally and on Streamlit Cloud.
    logo_path = Path(__file__).resolve().with_name("pm_logo_transparent.png")
    if logo_path.is_file():
        logo_b64 = base64.b64encode(logo_path.read_bytes()).decode("ascii")
        st.markdown(
            f'<div class="pm-login-brand" aria-hidden="true">'
            f'<img src="data:image/png;base64,{logo_b64}" alt="" />'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ----------------------------------------
    # 3. LOAD CONFIGURED USERS
    # ----------------------------------------

    try:
        users = st.secrets["auth"]["users"]

    except (KeyError, FileNotFoundError):
        st.error(
            "Login is not configured. "
            "Add [auth.users] to Streamlit secrets."
        )
        st.stop()

    if not users:
        st.error("No login users are configured.")
        st.stop()

    # ----------------------------------------
    # 4. LOGIN FORM
    # ----------------------------------------

    _, center, _ = st.columns([1, 1.4, 1])

    with center:

        st.title("AquaSpatial")

        st.caption("Geospatial Water Quality Intelligence")

        st.subheader("Secure access")

        st.write("Sign in to access GIS maps, sampling data and reports.")

        # ------------------------------------
        # 5. LOGIN ATTEMPT LIMIT
        # ------------------------------------

        failures = st.session_state.get("wq_login_failures", 0)

        locked_until = st.session_state.get("wq_locked_until", 0.0)

        if time.monotonic() < locked_until:

            st.error(
                "Too many unsuccessful attempts. "
                "Try again later."
            )

            st.stop()

        # ------------------------------------
        # 6. USERNAME AND PASSWORD
        # ------------------------------------

        with st.form("wq_login_form", clear_on_submit=True):

            username = st.text_input(
                "Username",
                max_chars=100
            ).strip()

            password = st.text_input(
                "Password",
                type="password"
            )

            submitted = st.form_submit_button(
                "Sign in",
                use_container_width=True,
                type="primary"
            )

        # ------------------------------------
        # 7. VERIFY CREDENTIALS
        # ------------------------------------

        if submitted:

            valid_username = bool(
                re.fullmatch(r"[A-Za-z0-9_.@-]{1,100}", username)
            )

            encoded = (
                users.get(username, "")
                if valid_username
                else ""
            )

            if (
                isinstance(encoded, str)
                and _verify_password(password, encoded)
            ):

                st.session_state["wq_authenticated"] = True

                st.session_state["wq_username"] = username

                st.session_state["wq_login_failures"] = 0

                st.session_state.pop(
                    "wq_locked_until",
                    None
                )

                st.rerun()

            else:

                failures += 1

                st.session_state["wq_login_failures"] = failures

                if failures >= 5:

                    st.session_state["wq_locked_until"] = (
                        time.monotonic() + 300
                    )

                    st.session_state["wq_login_failures"] = 0

                    st.error(
                        "Too many unsuccessful attempts. "
                        "Try again in about 5 minutes."
                    )

                else:

                    st.error(
                        "Invalid username or password."
                    )

    # ----------------------------------------
    # 8. PREVENT UNAUTHENTICATED ACCESS
    # ----------------------------------------

    st.stop()
