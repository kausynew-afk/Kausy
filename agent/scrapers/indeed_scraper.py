"""Indeed job scraper using Playwright."""

from __future__ import annotations

import logging
import urllib.parse
from typing import Any

from playwright.async_api import Page

from ..models import JobListing
from .base import BaseScraper

logger = logging.getLogger(__name__)

AGE_FILTER_MAP = {
    1: "1",
    3: "3",
    7: "7",
    14: "14",
    30: "",
}


class IndeedScraper(BaseScraper):
    """Scrapes Indeed's public job search results."""

    @property
    def platform_name(self) -> str:
        return "indeed"

    def _build_url(self, start: int = 0) -> str:
        profile = self.config["profile"]
        scraping = self.config["scraping"]

        params: dict[str, str] = {
            "q": profile["job_title"],
            "l": profile["location"],
            "start": str(start),
        }

        jtype = scraping.get("job_type", "")
        type_map = {"full-time": "fulltime", "part-time": "parttime", "contract": "contract"}
        if jtype in type_map:
            params["jt"] = type_map[jtype]

        days = scraping.get("posted_within_days", 7)
        closest = min(AGE_FILTER_MAP.keys(), key=lambda k: abs(k - days))
        if AGE_FILTER_MAP[closest]:
            params["fromage"] = AGE_FILTER_MAP[closest]

        radius = scraping.get("search_radius_miles", 50)
        params["radius"] = str(radius)

        return "https://www.indeed.com/jobs?" + urllib.parse.urlencode(params)

    async def _scrape_listings(self, page: Page) -> list[JobListing]:
        max_results = self.config["scraping"].get("max_results_per_platform", 25)
        listings: list[JobListing] = []
        start = 0

        while len(listings) < max_results:
            url = self._build_url(start)
            logger.info("Indeed: navigating to %s", url)
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await self._throttle()

            job_cards = await page.query_selector_all(
                "div.job_seen_beacon, div.jobsearch-ResultsList div.result, td.resultContent"
            )

            if not job_cards:
                logger.info("Indeed: no more cards found, stopping pagination")
                break

            for card in job_cards:
                if len(listings) >= max_results:
                    break
                try:
                    listing = await self._parse_card(card, page)
                    if listing:
                        listings.append(listing)
                except Exception:
                    logger.debug("Indeed: failed to parse a card, skipping")

            start += 10

        return listings

    async def _parse_card(self, card: Any, page: Page) -> JobListing | None:
        title_el = await card.query_selector(
            "h2.jobTitle a span, a.jcs-JobTitle span"
        )
        company_el = await card.query_selector(
            "span[data-testid='company-name'], span.css-63koeb"
        )
        location_el = await card.query_selector(
            "div[data-testid='text-location'], div.css-1p0sjhy"
        )
        link_el = await card.query_selector(
            "h2.jobTitle a, a.jcs-JobTitle"
        )

        title = (await title_el.inner_text()).strip() if title_el else None
        company = (await company_el.inner_text()).strip() if company_el else None
        location = (await location_el.inner_text()).strip() if location_el else ""
        href_raw = await link_el.get_attribute("href") if link_el else None

        if not title or not company or not href_raw:
            return None

        href = href_raw if href_raw.startswith("http") else f"https://www.indeed.com{href_raw}"

        description = await self._fetch_description(page, href)

        return JobListing(
            title=title,
            company=company,
            location=location,
            description=description,
            url=href.split("&")[0],
            platform="indeed",
        )

    async def _fetch_description(self, page: Page, url: str) -> str:
        try:
            detail_page = await page.context.new_page()
            await detail_page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await self._throttle()

            desc_el = await detail_page.query_selector(
                "div#jobDescriptionText, div.jobsearch-JobComponent-description"
            )
            description = (await desc_el.inner_text()).strip() if desc_el else ""
            await detail_page.close()
            return description
        except Exception:
            logger.debug("Indeed: couldn't fetch description for %s", url)
            return ""
