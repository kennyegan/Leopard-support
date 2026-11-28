"""Local operator tool; never sends invitations or changes provider spend grants."""

import argparse
from psycopg.types.json import Jsonb

from .db import connection


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["invite", "revoke"])
    parser.add_argument("email")
    parser.add_argument("--role", choices=["tester", "admin"], default="tester")
    parser.add_argument("--audience", choices=["student", "staff"], action="append", default=[])
    args = parser.parse_args()
    email = args.email.strip().lower()
    if "@" not in email or len(email) > 254:
        parser.error("A valid identity-provider email is required")
    with connection() as conn:
        if args.action == "invite":
            conn.execute(
                "INSERT INTO pilot_invites(email,role,knowledge_audiences) VALUES(%s,%s,%s) ON CONFLICT(email) DO UPDATE SET active=true,role=EXCLUDED.role,knowledge_audiences=EXCLUDED.knowledge_audiences",
                (email, args.role, Jsonb(["campus", *sorted(set(args.audience))])),
            )
        else:
            conn.execute("UPDATE pilot_invites SET active=false WHERE email=%s", (email,))
            conn.execute(
                "DELETE FROM pilot_logins WHERE user_id IN (SELECT id FROM pilot_users WHERE email=%s)",
                (email,),
            )
        conn.execute("INSERT INTO pilot_audit(event) VALUES(%s)", ("invitation_" + args.action,))
    print("Invitation allowlist updated locally. No message was sent.")


if __name__ == "__main__":
    main()
