
import hashlib
import secrets
import tkinter as tk
from tkinter import simpledialog, messagebox
from pathlib import Path
import tomllib

ITERATIONS = 600_000

root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)

password = simpledialog.askstring(
    "AquaSpatial",
    "Enter a new password (minimum 12 characters):",
    show="*",
    parent=root,
)

if password is None:
    root.destroy()
    raise SystemExit("Cancelled")

confirm = simpledialog.askstring(
    "AquaSpatial",
    "Confirm your password:",
    show="*",
    parent=root,
)

if confirm is None:
    root.destroy()
    raise SystemExit("Cancelled")

if password != confirm:
    messagebox.showerror(
        "AquaSpatial",
        "Passwords do not match.",
        parent=root,
    )
    root.destroy()
    raise SystemExit(1)

if len(password) < 12:
    messagebox.showerror(
        "AquaSpatial",
        "Use at least 12 characters.",
        parent=root,
    )
    root.destroy()
    raise SystemExit(1)

salt = secrets.token_bytes(16)
digest = hashlib.pbkdf2_hmac(
    "sha256",
    password.encode("utf-8"),
    salt,
    ITERATIONS,
)

encoded = (
    f"pbkdf2_sha256${ITERATIONS}$"
    f"{salt.hex()}${digest.hex()}"
)

secrets_path = (
    Path(__file__).resolve().parent
    / ".streamlit"
    / "secrets.toml"
)

secrets_path.parent.mkdir(parents=True, exist_ok=True)

# Preserve existing entries; fail safely on malformed TOML.
if secrets_path.exists():
    try:
        existing = tomllib.loads(
            secrets_path.read_text(encoding="utf-8-sig")
        )
    except tomllib.TOMLDecodeError:
        messagebox.showerror(
            "AquaSpatial",
            "Existing secrets.toml is malformed. "
            "Back it up and repair it before continuing.",
            parent=root,
        )
        root.destroy()
        raise SystemExit(1)

    if set(existing.keys()) - {"auth"} or (
        isinstance(existing.get("auth"), dict)
        and set(existing["auth"].keys()) - {"users"}
    ):
        messagebox.showerror(
            "AquaSpatial",
            "Other secrets are configured. "
            "Update the admin entry manually to preserve them.",
            parent=root,
        )
        root.destroy()
        raise SystemExit(1)

    users = existing.get("auth", {}).get("users", {})
    if not isinstance(users, dict):
        raise SystemExit("Invalid auth.users configuration")
else:
    users = {}

users["admin"] = encoded

# Preserve other users, if any.
content = "[auth.users]\n"
for username, hashed_password in users.items():
    if not isinstance(hashed_password, str):
        raise SystemExit("Invalid user hash entry")
    content += f'{username!r} = {hashed_password!r}\n'

# Write using a temporary file and replace the original.
temp_path = secrets_path.with_suffix(".toml.tmp")
temp_path.write_text(content, encoding="utf-8")
temp_path.replace(secrets_path)

messagebox.showinfo(
    "AquaSpatial",
    "Admin password saved successfully.\n"
    "Restart AquaSpatial and sign in.",
    parent=root,
)

root.destroy()
print("Admin password configuration saved.")
