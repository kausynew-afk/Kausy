"""Abstract base scraper with shared anti-detection and throttle logic."""

from __future__ import annotations

import asyncio
import logging
import random
from abc import ABC, abstractmethod
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from ..models import JobListing

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


class BaseScraper(ABC):
    """Base class for all job-platform scrapers."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.safety = config.get("safety", {})
        self._min_delay = self.safety.get("min_delay_seconds", 5)
        self._max_delay = self.safety.get("max_delay_seconds", 15)
        self._rotate_ua = self.safety.get("rotate_user_agents", True)

    def _pick_user_agent(self) -> str:
        return random.choice(USER_AGENTS) if self._rotate_ua else USER_AGENTS[0]

    async def _throttle(self) -> None:
        delay = random.uniform(self._min_delay, self._max_delay)
        logger.debug("Throttling for %.1f seconds", delay)
        await asyncio.sleep(delay)

    async def _create_context(self, browser: Browser) -> BrowserContext:
        return await browser.new_context(
            user_agent=self._pick_user_agent(),
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/New_York",
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            },
        )

    async def scrape(self) -> list[JobListing]:
        """Launch browser, scrape listings, return results."""
        listings: list[JobListing] = []
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--ignore-certificate-errors",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            context = await self._create_context(browser)
            page = await context.new_page()

            await page.route(
                "**/*.{png,jpg,jpeg,gif,svg,webp,woff,woff2,ttf,eot}",
                lambda route: route.abort(),
            )

            try:
                listings = await self._scrape_listings(page)
                logger.info(
                    "%s: scraped %d listings", self.platform_name, len(listings)
                )
            except Exception:
                logger.exception("%s: scraping failed", self.platform_name)
            finally:
                await context.close()
                await browser.close()

        return listings

    @property
    @abstractmethod
    def platform_name(self) -> str: ...

    @abstractmethod
    async def _scrape_listings(self, page: Page) -> list[JobListing]: ...
