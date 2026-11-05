"""Make the agent key and the admin password hash (python -m tools.zyber_secrets)."""

import argparse
import getpass
import secrets
import sys

from werkzeug.security import generate_password_hash

MIN_PASSWORD_LENGTH = 12


def make_agent_key():
    return secrets.token_hex(32)


def make_password_hash(password):
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Use a password of at least {MIN_PASSWORD_LENGTH} characters.")
    return generate_password_hash(password)


def main(argv=None, *, ask=getpass.getpass):
    parser = argparse.ArgumentParser(description="Make secrets for a hosted Zyber NOC.")
    parser.add_argument("command", choices=("agent-key", "password-hash"))
    args = parser.parse_args(argv)
    if args.command == "agent-key":
        print(make_agent_key())
        return 0
    password = ask("New admin password: ")
    if ask("Type it again: ") != password:
        print("The two passwords did not match. Nothing was made.", file=sys.stderr)
        return 1
    try:
        print(make_password_hash(password))
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
