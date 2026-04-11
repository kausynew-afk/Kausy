"""LinkedIn job scraper using Playwright."""

from __future__ import annotations

import logging
import urllib.parse
from typing import Any

from playwright.async_api import Page

from ..models import JobListing
from .base import BaseScraper

logger = logging.getLogger(__name__)

EXPERIENCE_LEVEL_MAP = {
    "entry": "2",
    "mid": "3",
    "senior": "4",
    "lead": "5",
}

JOB_TYPE_MAP = {
    "full-time": "F",
    "part-time": "P",
    "contract": "C",
    "remote": "2",
}

TIME_FILTER_MAP = {
    1: "r86400",
    7: "r604800",
    30: "r2592000",
}


class LinkedInScraper(BaseScraper):
    """Scrapes LinkedIn's public job search (no login required)."""

    @property
    def platform_name(self) -> str:
        return "linkedin"

    def _build_url(self) -> str:
        profile = self.config["profile"]
        scraping = self.config["scraping"]

        params: dict[str, str] = {
            "keywords": profile["job_title"],
            "location": profile["location"],
            "origin": "JOB_SEARCH_PAGE_SEARCH_BUTTON",
            "refresh": "true",
        }

        exp = scraping.get("experience_level", "")
        if exp in EXPERIENCE_LEVEL_MAP:
            params["f_E"] = EXPERIENCE_LEVEL_MAP[exp]

        jtype = scraping.get("job_type", "")
        if jtype in JOB_TYPE_MAP:
            params["f_JT"] = JOB_TYPE_MAP[jtype]

        days = scraping.get("posted_within_days", 7)
        closest = min(TIME_FILTER_MAP.keys(), key=lambda k: abs(k - days))
        params["f_TPR"] = TIME_FILTER_MAP[closest]

        return "https://www.linkedin.com/jobs/search/?" + urllib.parse.urlencode(params)

    async def _scrape_listings(self, page: Page) -> list[JobListing]:
        url = self._build_url()
        max_results = self.config["scraping"].get("max_results_per_platform", 25)
        listings: list[JobListing] = []

        logger.info("LinkedIn: navigating to %s", url)
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await self._throttle()

        for _ in range(3):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)

        job_cards = await page.query_selector_all(
            "div.base-card, li.result-card, div.job-search-card"
        )
        logger.info("LinkedIn: found %d raw cards", len(job_cards))

        for card in job_cards[:max_results]:
            try:
                listing = await self._parse_card(card, page)
                if listing:
                    listings.append(listing)
            except Exception:
                logger.debug("LinkedIn: failed to parse a card, skipping")

        return listings

    async def _parse_card(self, card: Any, page: Page) -> JobListing | None:
        title_el = await card.query_selector(
            "h3.base-search-card__title, span.sr-only"
        )
        company_el = await card.query_selector(
            "h4.base-search-card__subtitle, a.hidden-nested-link"
        )
        location_el = await card.query_selector(
            "span.job-search-card__location"
        )
        link_el = await card.query_selector("a.base-card__full-link, a")

        title = (await title_el.inner_text()).strip() if title_el else None
        company = (await company_el.inner_text()).strip() if company_el else None
        location = (await location_el.inner_text()).strip() if location_el else ""
        href = await link_el.get_attribute("href") if link_el else None

        if not title or not company or not href:
            return None

        description = await self._fetch_description(page, href)

        return JobListing(
            title=title,
            company=company,
            location=location,
            description=description,
            url=href.split("?")[0],
            platform="linkedin",
        )

    async def _fetch_description(self, page: Page, url: str) -> str:
        """Navigate to job detail page and extract the description."""
        try:
            detail_page = await page.context.new_page()
            await detail_page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await self._throttle()

            desc_el = await detail_page.query_selector(
                "div.show-more-less-html__markup, div.description__text"
            )
            description = (await desc_el.inner_text()).strip() if desc_el else ""
            await detail_page.close()
            return description
        except Exception:
            logger.debug("LinkedIn: couldn't fetch description for %s", url)
            return ""
