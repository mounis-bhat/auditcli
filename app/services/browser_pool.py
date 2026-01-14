"""Browser pool for efficient Chrome instance management using Playwright."""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from playwright.async_api import Browser, Playwright, async_playwright

from app.config.settings import get_config
from app.errors.exceptions import PlaywrightBrowsersNotInstalledError

logger = logging.getLogger(__name__)


def check_playwright_browsers_available() -> None:
    """
    Check if Playwright Chromium browser is installed.

    Raises:
        PlaywrightBrowsersNotInstalledError: If Chromium browser is not installed.
    """
    # Playwright stores browsers in different locations depending on OS
    # Default: ~/.cache/ms-playwright on Linux/macOS, %USERPROFILE%\AppData\Local\ms-playwright on Windows
    playwright_cache = Path.home() / ".cache" / "ms-playwright"
    if sys.platform == "win32":
        playwright_cache = Path.home() / "AppData" / "Local" / "ms-playwright"

    # Check if any chromium installation exists
    if not playwright_cache.exists():
        raise PlaywrightBrowsersNotInstalledError(
            "Playwright browsers not installed. Run: playwright install chromium"
        )

    # Look for chromium installation (can be chromium-* or chromium_headless_shell-*)
    chromium_dirs = list(playwright_cache.glob("chromium*"))
    if not chromium_dirs:
        raise PlaywrightBrowsersNotInstalledError(
            "Playwright Chromium not installed. Run: playwright install chromium"
        )

    logger.info(f"Playwright Chromium found at: {chromium_dirs[0]}")


@dataclass
class BrowserInstance:
    """Represents a managed browser instance."""

    browser: Browser
    cdp_port: int
    in_use: bool = False
    last_used: datetime = field(default_factory=lambda: datetime.now(UTC))
    use_count: int = 0

    def mark_in_use(self) -> None:
        """Mark browser as currently in use."""
        self.in_use = True
        self.use_count += 1

    def mark_available(self) -> None:
        """Mark browser as available."""
        self.in_use = False
        self.last_used = datetime.now(UTC)


class BrowserPool:
    """
    Pool of reusable browser instances for Lighthouse audits.

    Uses Playwright to manage Chrome instances with CDP (Chrome DevTools Protocol)
    ports that Lighthouse can connect to.
    """

    _instance: BrowserPool | None = None
    _lock = threading.Lock()

    def __init__(
        self,
        pool_size: int = 5,
        launch_timeout: int = 30,
        idle_timeout: int = 300,
    ):
        self.pool_size = pool_size
        self.launch_timeout = launch_timeout
        self.idle_timeout = idle_timeout

        self._playwright: Playwright | None = None
        self._browsers: list[BrowserInstance] = []
        self._pool_lock = asyncio.Lock()
        self._semaphore: asyncio.Semaphore | None = None
        self._next_port = 9222  # Starting CDP port
        self._initialized = False
        self._shutting_down = False

    @classmethod
    def get_instance(cls) -> BrowserPool:
        """Get or create the singleton browser pool."""
        with cls._lock:
            if cls._instance is None:
                config = get_config()
                cls._instance = cls(
                    pool_size=config.browser_pool_size,
                    launch_timeout=config.browser_launch_timeout,
                    idle_timeout=config.browser_idle_timeout,
                )
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (for testing)."""
        with cls._lock:
            cls._instance = None

    async def initialize(self) -> None:
        """Initialize the browser pool (lazy - doesn't launch browsers yet)."""
        if self._initialized:
            return

        async with self._pool_lock:
            if self._initialized:
                return

            # Validate Playwright browsers are installed before starting
            check_playwright_browsers_available()

            self._playwright = await async_playwright().start()
            self._semaphore = asyncio.Semaphore(self.pool_size)
            self._initialized = True
            logger.info(f"Browser pool initialized with capacity for {self.pool_size} browsers")

    async def _create_browser(self) -> BrowserInstance:
        """Create a new browser instance with CDP enabled."""
        if not self._playwright:
            raise RuntimeError("Browser pool not initialized")

        # Allocate a port for CDP
        port = self._next_port
        self._next_port += 1

        # Launch browser with CDP enabled
        browser = await asyncio.wait_for(
            self._playwright.chromium.launch(
                headless=True,
                args=[
                    f"--remote-debugging-port={port}",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            ),
            timeout=self.launch_timeout,
        )

        instance = BrowserInstance(browser=browser, cdp_port=port)
        logger.info(f"Created new browser instance on CDP port {port}")
        return instance

    async def _get_available_browser(self) -> BrowserInstance | None:
        """Get an available browser from the pool."""
        for instance in self._browsers:
            if not instance.in_use:
                # Check if browser is still connected
                if instance.browser.is_connected():
                    instance.mark_in_use()
                    return instance
                else:
                    # Browser disconnected, remove it
                    logger.warning(f"Browser on port {instance.cdp_port} disconnected, removing")
                    self._browsers.remove(instance)
        return None

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[BrowserInstance]:
        """
        Acquire a browser instance from the pool.

        Creates a new browser if needed and pool capacity allows.
        Blocks if pool is at capacity until a browser becomes available.
        """
        if not self._initialized:
            await self.initialize()

        if self._shutting_down:
            raise RuntimeError("Browser pool is shutting down")

        assert self._semaphore is not None

        # Wait for a slot in the pool
        await self._semaphore.acquire()

        instance: BrowserInstance | None = None
        try:
            async with self._pool_lock:
                # Try to get an existing available browser
                instance = await self._get_available_browser()

                # Create a new one if needed
                if instance is None:
                    instance = await self._create_browser()
                    instance.mark_in_use()
                    self._browsers.append(instance)

            yield instance

        finally:
            if instance:
                async with self._pool_lock:
                    instance.mark_available()
            self._semaphore.release()

    async def shutdown(self) -> None:
        """Shutdown the browser pool and close all browsers."""
        self._shutting_down = True

        async with self._pool_lock:
            for instance in self._browsers:
                try:
                    await instance.browser.close()
                    logger.info(f"Closed browser on port {instance.cdp_port}")
                except Exception as e:
                    logger.error(f"Error closing browser: {e}")

            self._browsers.clear()

            if self._playwright:
                await self._playwright.stop()
                self._playwright = None

        self._initialized = False
        self._shutting_down = False
        logger.info("Browser pool shutdown complete")

    async def cleanup_idle(self) -> int:
        """
        Close idle browsers that haven't been used recently.

        Returns the number of browsers closed.
        """
        now = datetime.now(UTC)
        closed_count = 0

        async with self._pool_lock:
            to_remove: list[BrowserInstance] = []
            for instance in self._browsers:
                if not instance.in_use:
                    idle_seconds = (now - instance.last_used).total_seconds()
                    if idle_seconds > self.idle_timeout:
                        to_remove.append(instance)

            for instance in to_remove:
                try:
                    idle_secs = (now - instance.last_used).total_seconds()
                    await instance.browser.close()
                    self._browsers.remove(instance)
                    closed_count += 1
                    logger.info(
                        f"Closed idle browser on port {instance.cdp_port} "
                        f"(idle for {idle_secs:.0f}s)"
                    )
                except Exception as e:
                    logger.error(f"Error closing idle browser: {e}")

        return closed_count

    def get_stats(self) -> dict[str, int]:
        """Get current pool statistics."""
        active = sum(1 for b in self._browsers if b.in_use)
        idle = sum(1 for b in self._browsers if not b.in_use)
        total_uses = sum(b.use_count for b in self._browsers)

        return {
            "active": active,
            "idle": idle,
            "total": len(self._browsers),
            "capacity": self.pool_size,
            "total_uses": total_uses,
        }

    @property
    def is_initialized(self) -> bool:
        """Check if the pool has been initialized."""
        return self._initialized
