import asyncio
from concurrent.futures import ThreadPoolExecutor


def run_async_test(coroutine_factory):
    """Run a coroutine on an isolated thread and event loop."""
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(coroutine_factory())).result()
