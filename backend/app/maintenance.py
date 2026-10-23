"""Retry expired/orphan object cleanup: python -m app.maintenance."""

import asyncio

from .main import create_app


async def main():
    app = create_app()
    async with app.router.lifespan_context(app):
        await app.state.workspaces.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
