import asyncio
import os

from banking.services.postgres_service import postgres_service


async def main():
    reset = os.getenv("BANKING_SEED_RESET", "false").lower() == "true"
    result = await postgres_service.seed_demo_data(reset=reset)
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
