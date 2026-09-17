"""Explicit connection check. Sends no workbook records to OCI."""
import asyncio
import sys

from .tools.model import OciModel


async def main():
    try:
        answer = await OciModel().complete("Reply with the word OK only.", {"purpose": "Python staffing backend connection check; no staffing records sent."})
        print("OCI inference responded:", answer[:100])
        return 0
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
