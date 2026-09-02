#!/usr/bin/env python3
"""Quick Azure SQL connectivity test."""

from __future__ import annotations

import sys

from config import BASE_DIR, DATABASE_URL


def main() -> int:
    print(f"Project root: {BASE_DIR}")
    print(f".env exists: {(BASE_DIR / '.env').exists()}")

    if not DATABASE_URL:
        print("ERROR: DATABASE_URL is empty.")
        print("Create .env in project root (next to README.md), not inside pipeline/.")
        return 1

    # Mask password in output
    safe = DATABASE_URL
    if "@" in DATABASE_URL and "://" in DATABASE_URL:
        prefix, rest = DATABASE_URL.split("://", 1)
        if "@" in rest:
            creds, host = rest.rsplit("@", 1)
            if ":" in creds:
                user = creds.split(":", 1)[0]
                safe = f"{prefix}://{user}:****@{host}"

    print(f"DATABASE_URL: {safe}")
    print("Connecting...")

    try:
        from db import get_connection

        with get_connection() as conn:
            row = conn.execute(__import__("sqlalchemy").text("SELECT 1 AS ok")).first()
            print(f"SUCCESS: connected (SELECT 1 => {row[0]})")
        return 0
    except Exception as e:
        print(f"FAILED: {e}")
        print()
        print("Common fixes:")
        print("  1. Azure Portal -> SQL Server hkrl8282 -> Networking")
        print("     Add your current public IP (search 'what is my ip')")
        print("  2. Ensure .env is at project root: 13f-analyzer/.env")
        print("  3. URL-encode special chars in password (@ # % -> %40 %23 %25)")
        print("  4. Disable VPN / try another network if corporate firewall blocks port 1433")
        return 1


if __name__ == "__main__":
    sys.exit(main())
