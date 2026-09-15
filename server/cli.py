"""
Server Administration CLI.
Provides the create-admin command to securely seed or update the administrative operator account.
Credentials are never hardcoded and can be passed via flags or entered interactively.
"""
import sys
import getpass
import argparse
import logging
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.database import init_db, SessionLocal
from server.models.entities import User, Profile
from server.services.auth import AuthService

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("server.cli")


def create_admin_user(
    email: str,
    password: str,
    full_name: str = "Admin Operator",
    db: Optional[Session] = None
) -> None:
    """Creates or updates an administrator user in the database."""
    session = db or SessionLocal()
    should_close = db is None
    try:
        clean_email = email.strip().lower()
        if not clean_email or "@" not in clean_email:
            raise ValueError(f"Invalid email address: {email}")
        if not password or len(password) < 8:
            raise ValueError("Password must be at least 8 characters long.")

        password_hash = AuthService.hash_password(password)

        user = session.execute(
            select(User).where(User.email == clean_email)
        ).scalar_one_or_none()

        if user:
            user.password_hash = password_hash
            user.is_active = True
            logger.info("Existing user %s updated with new password.", clean_email)
        else:
            user = User(
                email=clean_email,
                password_hash=password_hash,
                is_active=True
            )
            session.add(user)
            session.flush()

            profile = Profile(
                user_id=user.id,
                full_name=full_name,
                title="Security & Systems Engineer",
                email=clean_email
            )
            session.add(profile)
            logger.info("Admin user %s successfully created.", clean_email)

        session.commit()
    except Exception as e:
        session.rollback()
        logger.error("Failed to create/update admin user: %s", e)
        raise
    finally:
        if should_close:
            session.close()


def main():
    parser = argparse.ArgumentParser(description="Outbound Pipeline Server CLI Management")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # create-admin sub-command
    admin_parser = subparsers.add_parser("create-admin", help="Seed or update the admin operator account")
    admin_parser.add_argument("--email", type=str, required=True, help="Admin email address")
    admin_parser.add_argument("--password", type=str, default=None, help="Admin password (prompts securely if omitted)")
    admin_parser.add_argument("--name", type=str, default="Raghav Pathak", help="Admin operator full name")

    args = parser.parse_args()

    if args.command == "create-admin":
        password = args.password
        if not password:
            password = getpass.getpass(f"Enter password for {args.email}: ")
            confirm = getpass.getpass("Confirm password: ")
            if password != confirm:
                print("Error: Passwords do not match.", file=sys.stderr)
                sys.exit(1)

        try:
            create_admin_user(args.email, password, args.name)
            print(f"✓ Administrator account '{args.email}' is ready.")
        except Exception as e:
            print(f"✗ Failed: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
