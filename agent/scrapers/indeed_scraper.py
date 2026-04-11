"""Indeed job scraper using Playwright."""

from __future__ import annotations

import logging
import re
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

INDEED_DOMAIN_MAP = {
    "india": "https://in.indeed.com",
    "pune": "https://in.indeed.com",
    "mumbai": "https://in.indeed.com",
    "bangalore": "https://in.indeed.com",
    "delhi": "https://in.indeed.com",
    "hyderabad": "https://in.indeed.com",
    "chennai": "https://in.indeed.com",
    "kolkata": "https://in.indeed.com",
}


class IndeedScraper(BaseScraper):
    """Scrapes Indeed's public job search results."""

    @property
    def platform_name(self) -> str:
        return "indeed"

    def _get_base_url(self) -> str:
        """Pick the right Indeed domain based on location."""
        location = self.config["profile"].get("location", "").lower()
        for keyword, domain in INDEED_DOMAIN_MAP.items():
            if keyword in location:
                return domain
        return "https://www.indeed.com"

    def _build_url(self, start: int = 0) -> str:
        profile = self.config["profile"]
        scraping = self.config["scraping"]
        base = self._get_base_url()

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

        return f"{base}/jobs?" + urllib.parse.urlencode(params)

    async def _scrape_listings(self, page: Page) -> list[JobListing]:
        max_results = self.config["scraping"].get("max_results_per_platform", 25)
        listings: list[JobListing] = []
        start = 0
        base = self._get_base_url()

        while len(listings) < max_results:
            url = self._build_url(start)
            logger.info("Indeed: navigating to %s", url)
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await self._throttle()

            job_cards = await page.query_selector_all(
                "div.job_seen_beacon, div.jobsearch-ResultsList div.result, "
                "td.resultContent, div[class*='jobCard'], div[class*='job_seen']"
            )

            if not job_cards:
                logger.info("Indeed: no more cards found, stopping pagination")
                break

            logger.info("Indeed: found %d cards on page %d", len(job_cards), start // 10 + 1)

            for card in job_cards:
                if len(listings) >= max_results:
                    break
                try:
                    listing = await self._parse_card(card, page, base)
                    if listing:
                        listings.append(listing)
                except Exception:
                    logger.debug("Indeed: failed to parse a card, skipping")

            start += 10

        return listings

    async def _parse_card(self, card: Any, page: Page, base: str) -> JobListing | None:
        title_el = await card.query_selector(
            "h2.jobTitle a span, a.jcs-JobTitle span, "
            "h2 a span[id^='jobTitle'], span[title]"
        )
        company_el = await card.query_selector(
            "span[data-testid='company-name'], span.css-63koeb, "
            "span.companyName, a[data-tn-element='companyName']"
        )
        location_el = await card.query_selector(
            "div[data-testid='text-location'], div.css-1p0sjhy, "
            "div.companyLocation, span.companyLocation"
        )
        link_el = await card.query_selector(
            "h2.jobTitle a, a.jcs-JobTitle, h2 a"
        )

        title = (await title_el.inner_text()).strip() if title_el else None
        company = (await company_el.inner_text()).strip() if company_el else None
        location = (await location_el.inner_text()).strip() if location_el else ""
        href_raw = await link_el.get_attribute("href") if link_el else None

        if not title or not company or not href_raw:
            return None

        href = href_raw if href_raw.startswith("http") else f"{base}{href_raw}"

        description = await self._fetch_description(page, href)

        job_code = None
        match = re.search(r"jk=([a-f0-9]+)", href_raw)
        if match:
            job_code = f"IND-{match.group(1)}"

        return JobListing(
            title=title,
            company=company,
            location=location,
            description=description,
            url=href.split("&")[0],
            platform="indeed",
            job_code=job_code,
        )

    async def _fetch_description(self, page: Page, url: str) -> str:
        try:
            detail_page = await page.context.new_page()
            await detail_page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await self._throttle()

            desc_el = await detail_page.query_selector(
                "div#jobDescriptionText, div.jobsearch-JobComponent-description, "
                "div[class*='jobDescription'], div[id='jobDescriptionText']"
            )
            description = (await desc_el.inner_text()).strip() if desc_el else ""
            await detail_page.close()
            return description
        except Exception:
            logger.debug("Indeed: couldn't fetch description for %s", url)
            return ""
