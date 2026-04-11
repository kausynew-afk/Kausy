"""Naukri.com job scraper using Playwright."""

from __future__ import annotations

import logging
import urllib.parse
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

NAUKRI_JOB_TYPE = {
    "full-time": "fulltime",
    "part-time": "parttime",
    "contract": "contract",
    "remote": "workFromHome",
}


class NaukriScraper(BaseScraper):
    """Scrapes Naukri.com public job search results (India's largest job portal)."""

    @property
    def platform_name(self) -> str:
        return "naukri"

    def _build_url(self, page_num: int = 1) -> str:
        profile = self.config["profile"]
        scraping = self.config["scraping"]

        title_slug = profile["job_title"].lower().replace(" ", "-")

        location = profile.get("location", "")
        city = location.split(",")[0].strip().lower() if location else ""

        exp_level = scraping.get("experience_level", "mid")
        exp_min, exp_max = EXPERIENCE_MAP.get(exp_level, (3, 7))

        path = f"/{title_slug}-jobs"
        if city:
            path += f"-in-{city}"

        params: dict[str, str] = {
            "k": profile["job_title"],
            "l": city,
            "experience": f"{exp_min}",
            "nignbevent_src": "jobsearchDeskGNB",
        }

        jtype = scraping.get("job_type", "")
        if jtype in NAUKRI_JOB_TYPE:
            params["jobType"] = NAUKRI_JOB_TYPE[jtype]

        days = scraping.get("posted_within_days", 7)
        if days <= 1:
            params["jobAge"] = "1"
        elif days <= 3:
            params["jobAge"] = "3"
        elif days <= 7:
            params["jobAge"] = "7"
        elif days <= 15:
            params["jobAge"] = "15"
        else:
            params["jobAge"] = "30"

        if page_num > 1:
            params["pageNo"] = str(page_num)

        return "https://www.naukri.com" + path + "?" + urllib.parse.urlencode(params)

    async def _scrape_listings(self, page: Page) -> list[JobListing]:
        max_results = self.config["scraping"].get("max_results_per_platform", 25)
        listings: list[JobListing] = []
        page_num = 1
        max_pages = (max_results // 20) + 2

        while len(listings) < max_results and page_num <= max_pages:
            url = self._build_url(page_num)
            logger.info("Naukri: navigating to %s", url)

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception:
                logger.warning("Naukri: page load timed out for page %d", page_num)
                break

            await self._throttle()

            # Scroll to trigger lazy-loaded cards
            for _ in range(3):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1500)

            job_cards = await page.query_selector_all(
                "article.jobTuple, div.srp-jobtuple-wrapper, div.cust-job-tuple, "
                "div[class*='jobTuple'], div[data-job-id]"
            )

            if not job_cards:
                logger.info("Naukri: no cards found on page %d, stopping", page_num)
                break

            logger.info("Naukri: found %d cards on page %d", len(job_cards), page_num)

            for card in job_cards:
                if len(listings) >= max_results:
                    break
                try:
                    listing = await self._parse_card(card, page)
                    if listing:
                        listings.append(listing)
                except Exception:
                    logger.debug("Naukri: failed to parse a card, skipping")

            page_num += 1

        return listings

    async def _parse_card(self, card: Any, page: Page) -> JobListing | None:
        title_el = await card.query_selector(
            "a.title, a[class*='title'], h2 a, a[class*='jobTitle']"
        )
        company_el = await card.query_selector(
            "a.subTitle, a[class*='companyName'], span[class*='companyName'], "
            "a.comp-name, span.comp-name"
        )
        location_el = await card.query_selector(
            "span.locWdth, span[class*='location'], li.location, "
            "span[class*='loc'], span.loc"
        )
        exp_el = await card.query_selector(
            "span.expwdth, span[class*='experience'], li.experience, "
            "span[class*='exp']"
        )
        salary_el = await card.query_selector(
            "span.sal, span[class*='salary'], li.salary, "
            "span[class*='sal']"
        )

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

        description = await self._fetch_description(page, href)

        return JobListing(
            title=title,
            company=company,
            location=location,
            description=description,
            url=href.split("?")[0],
            platform="naukri",
            salary=salary,
            experience_level=experience,
        )

    async def _fetch_description(self, page: Page, url: str) -> str:
        """Navigate to Naukri job detail page and extract the full JD."""
        try:
            detail_page = await page.context.new_page()
            await detail_page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await self._throttle()

            desc_el = await detail_page.query_selector(
                "div.job-desc, div[class*='job-desc'], div[class*='jobDesc'], "
                "section.job-desc, div.dang-inner-html, "
                "div[class*='description'], section[class*='JobDescription']"
            )

            if not desc_el:
                desc_el = await detail_page.query_selector(
                    "div[class*='jd-container'], div[class*='about-company'], "
                    "div.other-details"
                )

            description = ""
            if desc_el:
                description = (await desc_el.inner_text()).strip()

            # Also grab key skills if available
            skills_el = await detail_page.query_selector(
                "div.key-skill, div[class*='keySkill'], div[class*='chip-container'], "
                "div[class*='tags-gt']"
            )
            if skills_el:
                skills_text = (await skills_el.inner_text()).strip()
                if skills_text:
                    description += f"\n\nKey Skills: {skills_text}"

            await detail_page.close()
            return description
        except Exception:
            logger.debug("Naukri: couldn't fetch description for %s", url)
            return ""
