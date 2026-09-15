import argparse
import json
import os


def main():
    parser = argparse.ArgumentParser(description="Read-only backend verification; no assignments, seed data or email.")
    parser.add_argument("check", choices=["database", "oci"])
    parser.add_argument("--env-file", help="Explicit configuration file. Never printed.")
    parser.add_argument("--live", action="store_true", help="Permit two OCI model requests with fixed non-personal test text.")
    args = parser.parse_args()
    # Smoke tests must not export even fixed test content to external tracing.
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    from app.config import Settings
    from app.errors import ServiceError
    try:
        settings = Settings(_env_file=args.env_file)
        if args.check == "database":
            from app.database import OracleDatabase
            database = OracleDatabase(settings)
            try:
                database.ping()
                print(json.dumps({"database": "reachable", "schema_verified": True, "writes": 0}))
            finally:
                database.close()
        else:
            if not args.live:
                parser.error("OCI smoke calls require --live; they can incur model usage.")
            from app.agents.oci_model import build_model
            from app.agents.smoke import run_smoke
            result = run_smoke(build_model(settings))
            if result["tool_result"] != {"allocation_pct": 40.0} or not result["final_received"]:
                raise ValueError("Unexpected interoperability result")
            print(json.dumps({"oci": "reachable", "tool_call": "passed", "langgraph": "passed", "allocation_pct": 40, "writes": 0}))
    except ServiceError as error:
        print(json.dumps({"error": error.code, "message": error.message}))
        raise SystemExit(1) from None
    except Exception as error:
        # SDK/config exceptions can contain endpoint/credential information. Keep output minimal.
        print(json.dumps({"error": "CHECK_FAILED", "type": type(error).__name__,
                          "message": "Check dependencies, configuration, network and model compatibility. No database writes were attempted."}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
