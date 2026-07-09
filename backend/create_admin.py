"""
create_admin.py

Run this once to create the first admin account:
    python create_admin.py

There's no self-service admin signup by design — admins are added by
whoever controls the server (you, during setup), the same way the
authorized voter list is controlled rather than open.

TROUBLESHOOTING — script appears to "freeze" after the password prompt:
getpass.getpass() deliberately shows NOTHING as you type (no characters,
no cursor movement) so the password can't be shoulder-surfed. That's
easy to mistake for a freeze — it isn't one; just type the password and
press Enter. If it's genuinely stuck and accepts no input at all, that
usually means your terminal doesn't support hidden input properly (this
happens in some IDE-integrated terminals and some Windows setups). In
that case, skip the interactive prompts entirely by passing the
username and password directly as arguments:

    python create_admin.py myusername mypassword

(Only use the argument form on a machine only you can see — anything
typed as a command-line argument can show up in shell history.)
"""

import sys
import getpass

from security.hashing import generate_salt, hash_with_salt
from database import queries


def create_admin(username: str, password: str):
    if queries.get_admin_by_username(username) is not None:
        print(f'An admin with username "{username}" already exists.')
        return
    salt = generate_salt()
    password_hash = hash_with_salt(password, salt)
    queries.insert_admin(username, password_hash, salt)
    print(f'Admin "{username}" created successfully.')


def main():
    if len(sys.argv) == 3:
        # Non-interactive mode: python create_admin.py <username> <password>
        create_admin(sys.argv[1], sys.argv[2])
        return

    username = input("New admin username: ").strip()
    try:
        password = getpass.getpass("New admin password (hidden — just type and press Enter): ")
    except Exception:
        # Some terminals can't do hidden input at all — fall back to plain
        # input() rather than hanging indefinitely.
        print("(Your terminal doesn't support hidden password input — it will be visible as you type.)")
        password = input("New admin password: ")

    create_admin(username, password)


if __name__ == "__main__":
    main()
