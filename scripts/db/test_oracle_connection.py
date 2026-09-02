import getpass
import os
import sys
import traceback

import oracledb


DB_USER = os.getenv("DB_USER")
DB_TNS_ALIAS = os.getenv("DB_TNS_ALIAS")
DB_WALLET_LOCATION = os.getenv("DB_WALLET_LOCATION")


def required(value, name):
    if not value:
        print(f"{name} is not configured.")
        sys.exit(1)
    return value


def run_app():
    user = required(DB_USER, "DB_USER")
    alias = required(DB_TNS_ALIAS, "DB_TNS_ALIAS")
    wallet_location = required(
        DB_WALLET_LOCATION,
        "DB_WALLET_LOCATION",
    )

    database_password = getpass.getpass(
        f"Database password for {user}: "
    )
    wallet_password = getpass.getpass(
        "Wallet password: "
    )

    pool = None

    try:
        pool = oracledb.create_pool(
            user=user,
            password=database_password,
            dsn=alias,
            config_dir=wallet_location,
            wallet_location=wallet_location,
            wallet_password=wallet_password,
            min=1,
            max=2,
            increment=1,
        )

        with pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        USER,
                        SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA'),
                        SYSDATE,
                        1
                    FROM DUAL
                    """
                )

                row = cursor.fetchone()

                print("\nConnected successfully!")
                print(f"Database user: {row[0]}")
                print(f"Current schema: {row[1]}")
                print(f"Database time: {row[2]}")
                print(f"Query result: {row[3]}")
                print(f"Thin mode: {oracledb.is_thin_mode()}")

                cursor.execute(
                    """
                    SELECT privilege
                    FROM session_privs
                    WHERE privilege IN (
                        'CREATE SESSION',
                        'CREATE TABLE',
                        'CREATE VIEW',
                        'CREATE SEQUENCE',
                        'CREATE PROCEDURE',
                        'UNLIMITED TABLESPACE'
                    )
                    ORDER BY privilege
                    """
                )

                privileges = [item[0] for item in cursor.fetchall()]

                print("\nRelevant privileges:")
                if privileges:
                    for privilege in privileges:
                        print(f"  - {privilege}")
                else:
                    print("  No relevant privileges found.")

                cursor.execute(
                    """
                    SELECT table_name
                    FROM user_tables
                    WHERE table_name LIKE 'AI_POD_%'
                    ORDER BY table_name
                    """
                )

                existing_tables = [
                    item[0] for item in cursor.fetchall()
                ]

                print("\nExisting AI Pod tables:")
                if existing_tables:
                    for table_name in existing_tables:
                        print(f"  - {table_name}")
                else:
                    print("  None")

    except oracledb.Error as error:
        print("\nCould not connect to Oracle Database.")
        print(f"Oracle error: {error}")
        sys.exit(1)

    except Exception:
        traceback.print_exc()
        sys.exit(1)

    finally:
        if pool is not None:
            pool.close(force=True)


if __name__ == "__main__":
    run_app()