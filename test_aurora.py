import asyncio
from tracker.scraper import fetch_jobs

async def main():
    url = "https://auroraer.com/careers/join-us"
    jobs = await fetch_jobs("aurora", url)
    print(f"Found {len(jobs) if jobs else 0} jobs")
    if jobs:
        for j in jobs[:5]:
            print(f"- {j['title']} : {j['link']}")

if __name__ == "__main__":
    asyncio.run(main())
