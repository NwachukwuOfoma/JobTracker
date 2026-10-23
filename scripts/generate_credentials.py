#!/usr/bin/env python3
"""generate_credentials.py

Utility script to store LinkedIn (and optionally Indeed) credentials securely
in the operating system's keychain/service using the `keyring` Python library.
The credentials are *not* written to the repository or any plain‑text file.
"""

import getpass
import sys

try:
    import keyring
except ImportError:
    sys.stderr.write("[ERROR] The 'keyring' package is not installed.\n")
    sys.stderr.write("You can install it with: pip install keyring\n")
    sys.exit(1)

SERVICE = "JobTracker_Linkedin"

def store_linkedin_credentials():
    """Prompt the user for LinkedIn username and password and store them
    securely using the OS keychain (macOS Keychain, Windows Credential
    Locker, or Secret Service on Linux)."""
    username = input("LinkedIn username (email): ").strip()
    if not username:
        sys.stderr.write("[ERROR] Username cannot be empty.\n")
        sys.exit(1)
    password = getpass.getpass("LinkedIn password: ")
    if not password:
        sys.stderr.write("[ERROR] Password cannot be empty.\n")
        sys.exit(1)

    # Store each piece separately so we can retrieve them individually.
    keyring.set_password(SERVICE, "username", username)
    keyring.set_password(SERVICE, "password", password)
    print("✅ LinkedIn credentials stored securely in the OS keychain.")

if __name__ == "__main__":
    print("--- LinkedIn Credential Setup ---")
    store_linkedin_credentials()
    # Future expansion: Indeed credentials could be stored under a different service.
