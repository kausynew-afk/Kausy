"""Naukri.com (www.naukri.com) job scraper — multi-keyword JSON API search."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from urllib.parse import quote

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
    """Scrapes www.naukri.com using their internal jobapi/v3/search endpoint
    with multiple search keywords for broader coverage."""

    @property
    def platform_name(self) -> str:
        return "naukri"

    def _get_search_keywords(self) -> list[str]:
        profile = self.config["profile"]
        keywords = profile.get("search_keywords", [])
        if not keywords:
            keywords = [profile.get("job_title", "Software Test Engineer")]
        return keywords

    def _build_api_url(self, keyword: str, page_num: int = 1) -> str:
        scraping = self.config["scraping"]
        location = self.config["profile"].get("location", "")
        city = location.split(",")[0].strip() if location else ""

        exp_level = scraping.get("experience_level", "mid")
        exp_min, exp_max = EXPERIENCE_MAP.get(exp_level, (3, 7))

        slug = keyword.lower().replace(" ", "-")
        city_slug = city.lower().replace(" ", "-") if city else ""

        params = {
            "noOfResults": 20,
            "urlType": "search_by_key_loc",
            "searchType": "adv",
            "keyword": quote(keyword),
            "location": quote(city),
            "pageNo": page_num,
            "experience": exp_min,
            "jobAge": scraping.get("posted_within_days", 14),
            "sort": "r",
            "seoKey": f"{slug}-jobs-in-{city_slug}" if city_slug else f"{slug}-jobs",
        }

        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"https://www.naukri.com/jobapi/v3/search?{query}"

    def _build_search_url(self, keyword: str, page_num: int = 1) -> str:
        """Fallback: path-based search URL for browser scraping."""
        scraping = self.config["scraping"]
        location = self.config["profile"].get("location", "")
        city = location.split(",")[0].strip().lower() if location else ""

        title_slug = keyword.lower().replace(" ", "-")
        exp_level = scraping.get("experience_level", "mid")
        exp_min, _ = EXPERIENCE_MAP.get(exp_level, (3, 7))

        path = f"/{title_slug}-jobs-in-{city}" if city else f"/{title_slug}-jobs"
        if page_num > 1:
            path += f"-{page_num}"

        params = f"?experience={exp_min}"
        days = scraping.get("posted_within_days", 14)
        params += f"&jobAge={days}"

        return f"https://www.naukri.com{path}{params}"

    async def _scrape_listings(self, page: Page) -> list[JobListing]:
        max_results = self.config["scraping"].get("max_results_per_platform", 25)
        keywords = self._get_search_keywords()
        all_listings: list[JobListing] = []
        seen_urls: set[str] = set()

        per_keyword = max(3, max_results // len(keywords))

        # Navigate to naukri.com once to establish origin for API calls
        try:
            await page.goto("https://www.naukri.com", wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)
        except Exception:
            logger.warning("Naukri: could not load homepage, trying browser fallback")
            return await self._scrape_via_browser_all(page, keywords, max_results)

        for keyword in keywords:
            if len(all_listings) >= max_results:
                break

            logger.info("Naukri API: searching for '%s'", keyword)
            keyword_listings = await self._scrape_keyword_api(page, keyword, per_keyword)

            for listing in keyword_listings:
                if len(all_listings) >= max_results:
                    break
                if listing.url not in seen_urls:
                    seen_urls.add(listing.url)
                    all_listings.append(listing)

        if not all_listings:
            logger.info("Naukri API: 0 results across all keywords, trying browser fallback")
            all_listings = await self._scrape_via_browser_all(page, keywords, max_results)

        return all_listings

    async def _scrape_keyword_api(self, page: Page, keyword: str, max_per: int) -> list[JobListing]:
        """Search for one keyword via the JSON API."""
        listings: list[JobListing] = []
        page_num = 1
        max_pages = 3

        while len(listings) < max_per and page_num <= max_pages:
            api_url = self._build_api_url(keyword, page_num)

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
                logger.warning("Naukri API: failed for '%s' page %d: %s", keyword, page_num, e)
                break

            job_details = data.get("jobDetails", [])
            if not job_details:
                logger.info("Naukri API: no jobs for '%s' page %d", keyword, page_num)
                break

            logger.info("Naukri API: got %d jobs for '%s' page %d", len(job_details), keyword, page_num)

            for job_data in job_details:
                if len(listings) >= max_per:
                    break
                if job_data.get("type") == "ads" or not job_data.get("title"):
                    continue
                listing = self._parse_api_job(job_data)
                if listing:
                    listings.append(listing)

            page_num += 1
            await self._throttle()

        return listings

    def _parse_api_job(self, job: dict) -> JobListing | None:
        title = job.get("title", "").strip()
        company = job.get("companyName", "").strip()
        jd_url = job.get("jdURL", "")

        if not title or not company:
            return None

        if jd_url and not jd_url.startswith("http"):
            jd_url = f"https://www.naukri.com{jd_url}"

        location_parts = []
        salary = ""
        experience = ""
        for ph in job.get("placeholders", []):
            ph_type = ph.get("type", "")
            if ph_type == "location":
                location_parts.append(ph.get("label", ""))
            elif ph_type == "salary":
                salary = ph.get("label", "")
            elif ph_type == "experience":
                experience = ph.get("label", "")

        location = ", ".join(location_parts) if location_parts else ""
        description = job.get("jobDescription", "")
        tags = job.get("tagsAndSkills", "")
        if tags:
            description += f"\n\nKey Skills: {tags}"

        job_code = job.get("jobId", "")
        if job_code:
            job_code = f"NK-{job_code}"

        return JobListing(
            title=title,
            company=company,
            location=location,
            description=description,
            url=jd_url.split("?")[0] if jd_url else "",
            platform="naukri",
            salary=salary or None,
            experience_level=experience or None,
            job_code=job_code or None,
        )

    async def _scrape_via_browser_all(self, page: Page, keywords: list[str], max_results: int) -> list[JobListing]:
        """Fallback: browser-based scraping across multiple keywords."""
        all_listings: list[JobListing] = []
        seen_urls: set[str] = set()
        per_keyword = max(3, max_results // len(keywords))

        for keyword in keywords:
            if len(all_listings) >= max_results:
                break

            logger.info("Naukri browser: searching for '%s'", keyword)
            page_num = 1

            while len(all_listings) < max_results and page_num <= 2:
                url = self._build_search_url(keyword, page_num)
                logger.info("Naukri browser: navigating to %s", url)

                try:
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                except Exception:
                    logger.warning("Naukri browser: timed out for '%s'", keyword)
                    break

                await self._throttle()

                for _ in range(3):
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(1500)

                job_cards = await page.query_selector_all(
                    "div.srp-jobtuple-wrapper, "
                    "article.jobTuple, "
                    "div[class*='jobTuple'], "
                    "div[data-job-id]"
                )

                if not job_cards:
                    break

                logger.info("Naukri browser: %d cards for '%s'", len(job_cards), keyword)
                count = 0
                for card in job_cards:
                    if count >= per_keyword or len(all_listings) >= max_results:
                        break
                    try:
                        listing = await self._parse_browser_card(card)
                        if listing and listing.url not in seen_urls:
                            seen_urls.add(listing.url)
                            all_listings.append(listing)
                            count += 1
                    except Exception:
                        pass

                page_num += 1

        return all_listings

    async def _parse_browser_card(self, card: Any) -> JobListing | None:
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

        job_id = await card.get_attribute("data-job-id")
        job_code = f"NK-{job_id}" if job_id else None

        return JobListing(
            title=title,
            company=company,
            location=location,
            description=f"Key Skills: {tags}" if tags else "",
            url=href.split("?")[0],
            platform="naukri",
            salary=salary,
            experience_level=experience,
            job_code=job_code,
        )
