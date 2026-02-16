"""Small script to test the running backend endpoints (requires backend running at localhost:8000)."""
import asyncio
import httpx


async def main():
    async with httpx.AsyncClient() as client:
        r = await client.post('http://localhost:8000/api/send-otp', json={'contact': 'dev@example.com', 'via': 'email'})
        print('send-otp', r.status_code, r.text)
        # Can't verify until we see printed OTP in logs for noop email sender


if __name__ == '__main__':
    asyncio.run(main())
