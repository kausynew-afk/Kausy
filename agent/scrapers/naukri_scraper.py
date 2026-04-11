"""Naukri.com (www.naukri.com) job scraper using their internal JSON API."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any

from playwright.async_api import Page

from ..models import JobListing
from .base import BaseScraper

logger = logging.getLogger(__name__)

EXPERIENCE_MAP = {
    "entry": (0, 2),
    "mid": (3, 7),
    "senior": (8, 12),
    "lead": (10, 20),
}


class NaukriScraper(BaseScraper):
    """Scrapes www.naukri.com using their internal jobapi/v3/search endpoint.

    Naukri aggressively blocks headless browsers on their search pages,
    so we use their JSON API directly which returns structured job data
    without needing to parse HTML.
    """

    @property
    def platform_name(self) -> str:
        return "naukri"

    def _build_api_url(self, page_num: int = 1) -> str:
        profile = self.config["profile"]
        scraping = self.config["scraping"]

        keyword = profile["job_title"]
        location = profile.get("location", "")
        city = location.split(",")[0].strip() if location else ""

        exp_level = scraping.get("experience_level", "mid")
        exp_min, exp_max = EXPERIENCE_MAP.get(exp_level, (3, 7))

        params = {
            "noOfResults": 20,
            "urlType": "search_by_key_loc",
            "searchType": "adv",
            "keyword": keyword,
            "location": city,
            "pageNo": page_num,
            "experience": exp_min,
            "jobAge": scraping.get("posted_within_days", 7),
            "sort": "r",
            "seoKey": f"{keyword.lower().replace(' ', '-')}-jobs-in-{city.lower()}",
        }

        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"https://www.naukri.com/jobapi/v3/search?{query}"

    def _build_search_url(self, page_num: int = 1) -> str:
        """Fallback: path-based search URL for browser scraping."""
        profile = self.config["profile"]
        scraping = self.config["scraping"]

        title_slug = profile["job_title"].lower().replace(" ", "-")
        location = profile.get("location", "")
        city = location.split(",")[0].strip().lower() if location else ""

        exp_level = scraping.get("experience_level", "mid")
        exp_min, _ = EXPERIENCE_MAP.get(exp_level, (3, 7))

        path = f"/{title_slug}-jobs-in-{city}" if city else f"/{title_slug}-jobs"
        if page_num > 1:
            path += f"-{page_num}"

        params = f"?experience={exp_min}"
        days = scraping.get("posted_within_days", 7)
        params += f"&jobAge={days}"

        return f"https://www.naukri.com{path}{params}"

    async def _scrape_listings(self, page: Page) -> list[JobListing]:
        max_results = self.config["scraping"].get("max_results_per_platform", 25)

        # Strategy 1: Try the JSON API first (most reliable)
        listings = await self._scrape_via_api(page, max_results)
        if listings:
            return listings

        # Strategy 2: Fallback to browser scraping with path-based URLs
        logger.info("Naukri: API returned no results, trying browser scraping")
        return await self._scrape_via_browser(page, max_results)

    async def _scrape_via_api(self, page: Page, max_results: int) -> list[JobListing]:
        """Use Naukri's internal JSON API to fetch job listings."""
        listings: list[JobListing] = []
        page_num = 1
        max_pages = (max_results // 20) + 2

        # Navigate to naukri.com first so fetch runs on same origin (avoids CORS)
        try:
            await page.goto("https://www.naukri.com", wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)
        except Exception:
            logger.warning("Naukri API: could not load naukri.com homepage")
            return []

        while len(listings) < max_results and page_num <= max_pages:
            api_url = self._build_api_url(page_num)
            logger.info("Naukri API: requesting page %d", page_num)

            try:
                response = await page.evaluate("""
                    async (url) => {
                        const resp = await fetch(url, {
                            headers: {
                                'Accept': 'application/json',
                                'Content-Type': 'application/json',
                                'appid': '109',
                                'systemid': 'Naukri',
                                'gid': 'LOCATION,INDUSTRY,EDUCATION,FAREA_ROLE',
                            }
                        });
                        return await resp.text();
                    }
                """, api_url)

                data = json.loads(response)
            except Exception as e:
                logger.warning("Naukri API: failed on page %d: %s", page_num, e)
                break

            job_details = data.get("jobDetails", [])
            if not job_details:
                logger.info("Naukri API: no jobs returned on page %d", page_num)
                break

            logger.info("Naukri API: got %d jobs on page %d", len(job_details), page_num)

            for job_data in job_details:
                if len(listings) >= max_results:
                    break

                # Skip promoted/ad entries that lack real data
                if job_data.get("type") == "ads" or not job_data.get("title"):
                    continue

                listing = self._parse_api_job(job_data)
                if listing:
                    listings.append(listing)

            page_num += 1
            await self._throttle()

        return listings

    def _parse_api_job(self, job: dict) -> JobListing | None:
        """Parse a job entry from the Naukri API response."""
        title = job.get("title", "").strip()
        company = job.get("companyName", "").strip()
        jd_url = job.get("jdURL", "")

        if not title or not company:
            return None

        if jd_url and not jd_url.startswith("http"):
            jd_url = f"https://www.naukri.com{jd_url}"

        location_parts = []
        for loc in job.get("placeholders", []):
            if loc.get("type") == "location":
                location_parts.append(loc.get("label", ""))
        location = ", ".join(location_parts) if location_parts else ""

        salary = ""
        experience = ""
        for ph in job.get("placeholders", []):
            if ph.get("type") == "salary":
                salary = ph.get("label", "")
            elif ph.get("type") == "experience":
                experience = ph.get("label", "")

        description = job.get("jobDescription", "")

        tags = job.get("tagsAndSkills", "")
        if tags:
            description += f"\n\nKey Skills: {tags}"

        return JobListing(
            title=title,
            company=company,
            location=location,
            description=description,
            url=jd_url.split("?")[0] if jd_url else "",
            platform="naukri",
            salary=salary or None,
            experience_level=experience or None,
        )

    async def _scrape_via_browser(self, page: Page, max_results: int) -> list[JobListing]:
        """Fallback: scrape Naukri using browser with path-based URLs."""
        listings: list[JobListing] = []
        page_num = 1
        max_pages = (max_results // 20) + 2

        while len(listings) < max_results and page_num <= max_pages:
            url = self._build_search_url(page_num)
            logger.info("Naukri browser: navigating to %s", url)

            try:
                await page.goto(url, wait_until="networkidle", timeout=30000)
            except Exception:
                logger.warning("Naukri browser: timed out on page %d", page_num)
                break

            await self._throttle()

            for _ in range(4):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000)

            job_cards = await page.query_selector_all(
                "div.srp-jobtuple-wrapper, "
                "article.jobTuple, "
                "div[class*='jobTuple'], "
                "div[data-job-id]"
            )

            if not job_cards:
                logger.info("Naukri browser: no cards on page %d", page_num)
                break

            logger.info("Naukri browser: found %d cards on page %d", len(job_cards), page_num)

            for card in job_cards:
                if len(listings) >= max_results:
                    break
                try:
                    listing = await self._parse_browser_card(card)
                    if listing:
                        listings.append(listing)
                except Exception:
                    logger.debug("Naukri browser: card parse failed, skipping")

            page_num += 1

        return listings

    async def _parse_browser_card(self, card: Any) -> JobListing | None:
        """Parse a job card from the browser DOM."""
        title_el = await card.query_selector("a.title, a.comp-name, h2 a")
        company_el = await card.query_selector("a.comp-name, a.subTitle, span.comp-name")
        location_el = await card.query_selector("span.loc-wrap, span.loc, span.locWdth")
        exp_el = await card.query_selector("span.exp-wrap, span.expwdth")
        salary_el = await card.query_selector("span.sal-wrap, span.sal")

        title = (await title_el.inner_text()).strip() if title_el else None
        company = (await company_el.inner_text()).strip() if company_el else None
        location = (await location_el.inner_text()).strip() if location_el else ""
        experience = (await exp_el.inner_text()).strip() if exp_el else None
        salary = (await salary_el.inner_text()).strip() if salary_el else None

        href = await title_el.get_attribute("href") if title_el else None
        if not title or not company or not href:
            return None

        if not href.startswith("http"):
            href = f"https://www.naukri.com{href}"

        tags_el = await card.query_selector("ul.tags-gt, div.tags-gt")
        tags = (await tags_el.inner_text()).strip() if tags_el else ""

        return JobListing(
            title=title,
            company=company,
            location=location,
            description=f"Key Skills: {tags}" if tags else "",
            url=href.split("?")[0],
            platform="naukri",
            salary=salary,
            experience_level=experience,
        )
