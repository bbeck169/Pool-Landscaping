"""Directory-catalogue seed for the Directories Subsystem (Phase D1).

Ships a curated list of 60 business directories used by the platform's
NAP-consistency + citation-management workflow. The seed is idempotent
— re-run reads (never overwrites) existing rows keyed on ``slug``.

Categories used downstream:
  * ``maps``           — Google Business Profile, Bing Places, Apple Maps
  * ``aggregator``     — Yelp, Facebook, and the wholesale data
                          aggregators that feed dozens of downstream sites.
  * ``general``        — BBB, YellowPages, WhitePages, Foursquare …
  * ``industry_pool``  — Pool-specific verticals.
  * ``industry_landscape`` — Landscaping-specific verticals.
  * ``review``         — Trustpilot, Sitejabber, ConsumerAffairs …
  * ``local``          — Nextdoor, Alignable, Chamber of Commerce …
  * ``social``         — Instagram Business, LinkedIn Company, TikTok Biz.
"""
from __future__ import annotations

from typing import List, Dict, Any

from config import db, logger
from utils import new_id, now_iso


# ─── Curated catalogue ─────────────────────────────────────────────────
# Each entry: slug, name, category, submission_url, homepage_url,
# priority (1=highest business-impact, 5=long-tail), requires_manual,
# requires_paid_account, expected_fields, scrape_url_template, notes.
#
# ``expected_fields`` drives the CSV-export template.
# ``scrape_url_template`` is populated only when we have (or can add)
# a working scraper adapter. Left blank means "no automated NAP scan
# yet — status is manual-only".

_EXPECTED_CORE = ["name", "address", "phone", "website"]
_EXPECTED_STD = _EXPECTED_CORE + ["category", "hours", "description"]
_EXPECTED_FULL = _EXPECTED_STD + ["logo", "photos"]


CATALOG: List[Dict[str, Any]] = [
    # ── Maps (top-of-funnel discovery) ────────────────────────────────
    {"slug": "google-business-profile", "name": "Google Business Profile",
      "category": "maps",
      "submission_url": "https://www.google.com/business/",
      "homepage_url":   "https://maps.google.com/",
      "priority": 1, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_FULL,
      "scrape_url_template": "https://www.google.com/search?q={name}+{city}",
      "notes": "Highest-impact citation. Requires ownership verification."},
    {"slug": "bing-places", "name": "Bing Places for Business",
      "category": "maps",
      "submission_url": "https://www.bingplaces.com/",
      "homepage_url":   "https://www.bing.com/maps",
      "priority": 1, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_FULL,
      "scrape_url_template": "", "notes": "Import from GBP is supported."},
    {"slug": "apple-maps-business",  "name": "Apple Business Connect",
      "category": "maps",
      "submission_url": "https://businessconnect.apple.com/",
      "homepage_url":   "https://maps.apple.com/",
      "priority": 1, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_FULL,
      "scrape_url_template": "", "notes": "iOS default map — critical for mobile."},

    # ── Aggregators / high-authority ──────────────────────────────────
    {"slug": "yelp", "name": "Yelp for Business",
      "category": "aggregator",
      "submission_url": "https://biz.yelp.com/signup",
      "homepage_url":   "https://www.yelp.com/",
      "priority": 1, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_FULL,
      "scrape_url_template": "https://www.yelp.com/biz/{slug_hint}",
      "notes": "Adapter present in review_scraper."},
    {"slug": "facebook-business", "name": "Facebook Business Page",
      "category": "aggregator",
      "submission_url": "https://www.facebook.com/business/pages",
      "homepage_url":   "https://www.facebook.com/",
      "priority": 1, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_FULL,
      "scrape_url_template": "https://www.facebook.com/{slug_hint}",
      "notes": "Also feeds Instagram + Meta ad review."},
    {"slug": "foursquare", "name": "Foursquare City Guide",
      "category": "aggregator",
      "submission_url": "https://foursquare.com/city-guide/add-place",
      "homepage_url":   "https://foursquare.com/",
      "priority": 2, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_STD,
      "scrape_url_template": "", "notes": "Also feeds many downstream sites."},

    # ── General directories ───────────────────────────────────────────
    {"slug": "bbb", "name": "Better Business Bureau",
      "category": "general",
      "submission_url": "https://www.bbb.org/get-accredited",
      "homepage_url":   "https://www.bbb.org/",
      "priority": 2, "requires_manual": True, "requires_paid_account": True,
      "expected_fields": _EXPECTED_STD,
      "scrape_url_template": "", "notes": "Accreditation is paid; a free unaccredited profile exists."},
    {"slug": "yellowpages", "name": "YellowPages.com",
      "category": "general",
      "submission_url": "https://accounts.yellowpages.com/register",
      "homepage_url":   "https://www.yellowpages.com/",
      "priority": 3, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_STD,
      "scrape_url_template": "", "notes": "Legacy but still crawled."},
    {"slug": "whitepages", "name": "WhitePages Business",
      "category": "general",
      "submission_url": "https://business.whitepages.com/",
      "homepage_url":   "https://www.whitepages.com/",
      "priority": 4, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_CORE,
      "scrape_url_template": "", "notes": ""},
    {"slug": "superpages", "name": "Superpages",
      "category": "general",
      "submission_url": "https://accounts.superpages.com/register",
      "homepage_url":   "https://www.superpages.com/",
      "priority": 4, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_STD,
      "scrape_url_template": "", "notes": ""},
    {"slug": "manta", "name": "Manta",
      "category": "general",
      "submission_url": "https://www.manta.com/claim",
      "homepage_url":   "https://www.manta.com/",
      "priority": 4, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_STD,
      "scrape_url_template": "", "notes": ""},
    {"slug": "hotfrog", "name": "Hotfrog",
      "category": "general",
      "submission_url": "https://www.hotfrog.com/add-your-business",
      "homepage_url":   "https://www.hotfrog.com/",
      "priority": 5, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_CORE + ["category", "description"],
      "scrape_url_template": "", "notes": ""},
    {"slug": "brownbook", "name": "Brownbook.net",
      "category": "general",
      "submission_url": "https://www.brownbook.net/business/add",
      "homepage_url":   "https://www.brownbook.net/",
      "priority": 5, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_CORE + ["description"],
      "scrape_url_template": "", "notes": ""},
    {"slug": "cylex", "name": "Cylex US",
      "category": "general",
      "submission_url": "https://www.cylex.us.com/",
      "homepage_url":   "https://www.cylex.us.com/",
      "priority": 5, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_CORE + ["description"],
      "scrape_url_template": "", "notes": ""},
    {"slug": "citysearch", "name": "Citysearch",
      "category": "general",
      "submission_url": "https://www.citysearch.com/",
      "homepage_url":   "https://www.citysearch.com/",
      "priority": 4, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_STD,
      "scrape_url_template": "", "notes": ""},
    {"slug": "merchant-circle", "name": "MerchantCircle",
      "category": "general",
      "submission_url": "https://www.merchantcircle.com/business/signup",
      "homepage_url":   "https://www.merchantcircle.com/",
      "priority": 5, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_STD,
      "scrape_url_template": "", "notes": ""},
    {"slug": "ezlocal", "name": "eZlocal",
      "category": "general",
      "submission_url": "https://ezlocal.com/add-listing",
      "homepage_url":   "https://ezlocal.com/",
      "priority": 5, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_CORE,
      "scrape_url_template": "", "notes": ""},
    {"slug": "showmelocal", "name": "ShowMeLocal",
      "category": "general",
      "submission_url": "https://www.showmelocal.com/business/add",
      "homepage_url":   "https://www.showmelocal.com/",
      "priority": 5, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_CORE,
      "scrape_url_template": "", "notes": ""},
    {"slug": "elocal", "name": "eLocal",
      "category": "general",
      "submission_url": "https://www.elocal.com/business",
      "homepage_url":   "https://www.elocal.com/",
      "priority": 4, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_STD,
      "scrape_url_template": "", "notes": ""},
    {"slug": "n49", "name": "n49",
      "category": "general",
      "submission_url": "https://n49.com/business/add",
      "homepage_url":   "https://n49.com/",
      "priority": 5, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_STD,
      "scrape_url_template": "", "notes": ""},
    {"slug": "chamberofcommerce-com", "name": "ChamberofCommerce.com",
      "category": "general",
      "submission_url": "https://www.chamberofcommerce.com/",
      "homepage_url":   "https://www.chamberofcommerce.com/",
      "priority": 4, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_STD,
      "scrape_url_template": "", "notes": ""},
    {"slug": "insiderpages", "name": "InsiderPages",
      "category": "general",
      "submission_url": "https://www.insiderpages.com/",
      "homepage_url":   "https://www.insiderpages.com/",
      "priority": 5, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_CORE,
      "scrape_url_template": "", "notes": ""},

    # ── Industry · Pool + Spa ─────────────────────────────────────────
    {"slug": "poolspa-news", "name": "Pool & Spa News Directory",
      "category": "industry_pool",
      "submission_url": "https://www.poolspanews.com/",
      "homepage_url":   "https://www.poolspanews.com/",
      "priority": 3, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_STD,
      "scrape_url_template": "", "notes": "Industry publication directory."},
    {"slug": "aqua-magazine", "name": "AQUA Magazine",
      "category": "industry_pool",
      "submission_url": "https://aquamagazine.com/",
      "homepage_url":   "https://aquamagazine.com/",
      "priority": 4, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_STD,
      "scrape_url_template": "", "notes": ""},
    {"slug": "pool-mate", "name": "PoolMate Pro Locator",
      "category": "industry_pool",
      "submission_url": "https://poolmate.com/pro-locator",
      "homepage_url":   "https://poolmate.com/",
      "priority": 4, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_STD,
      "scrape_url_template": "", "notes": ""},
    {"slug": "apsp", "name": "Pool & Hot Tub Alliance (PHTA/APSP)",
      "category": "industry_pool",
      "submission_url": "https://www.phta.org/membership/",
      "homepage_url":   "https://www.phta.org/",
      "priority": 3, "requires_manual": True, "requires_paid_account": True,
      "expected_fields": _EXPECTED_STD,
      "scrape_url_template": "", "notes": "Membership fee required."},
    {"slug": "poolcorp-pro", "name": "PoolCorp Pro Locator",
      "category": "industry_pool",
      "submission_url": "https://www.poolcorp.com/",
      "homepage_url":   "https://www.poolcorp.com/",
      "priority": 5, "requires_manual": True, "requires_paid_account": True,
      "expected_fields": _EXPECTED_CORE,
      "scrape_url_template": "", "notes": ""},
    {"slug": "swimuniversity-pro", "name": "Swim University Pro Finder",
      "category": "industry_pool",
      "submission_url": "https://www.swimuniversity.com/",
      "homepage_url":   "https://www.swimuniversity.com/",
      "priority": 5, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_CORE,
      "scrape_url_template": "", "notes": ""},
    {"slug": "houzz-pool-pro", "name": "Houzz — Pool Professionals",
      "category": "industry_pool",
      "submission_url": "https://www.houzz.com/professionals/join",
      "homepage_url":   "https://www.houzz.com/",
      "priority": 3, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_FULL,
      "scrape_url_template": "", "notes": "Photos are the primary ranking signal here."},
    {"slug": "porch-pool", "name": "Porch — Pool Services",
      "category": "industry_pool",
      "submission_url": "https://porch.com/pro/signup",
      "homepage_url":   "https://porch.com/",
      "priority": 4, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_STD,
      "scrape_url_template": "", "notes": ""},
    {"slug": "homeguide-pool", "name": "HomeGuide — Pool Service",
      "category": "industry_pool",
      "submission_url": "https://homeguide.com/pros/join",
      "homepage_url":   "https://homeguide.com/",
      "priority": 4, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_STD,
      "scrape_url_template": "", "notes": ""},
    {"slug": "thumbtack-pool", "name": "Thumbtack — Pool Service",
      "category": "industry_pool",
      "submission_url": "https://www.thumbtack.com/pro",
      "homepage_url":   "https://www.thumbtack.com/",
      "priority": 3, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_STD,
      "scrape_url_template": "", "notes": "Lead-gen; paid per contact."},
    {"slug": "angi-pool", "name": "Angi — Pool Cleaning & Repair",
      "category": "industry_pool",
      "submission_url": "https://pros.angi.com/",
      "homepage_url":   "https://www.angi.com/",
      "priority": 3, "requires_manual": True, "requires_paid_account": True,
      "expected_fields": _EXPECTED_FULL,
      "scrape_url_template": "", "notes": "Formerly Angie's List / HomeAdvisor."},

    # ── Industry · Landscape ──────────────────────────────────────────
    {"slug": "angi-landscape", "name": "Angi — Landscaping",
      "category": "industry_landscape",
      "submission_url": "https://pros.angi.com/",
      "homepage_url":   "https://www.angi.com/",
      "priority": 3, "requires_manual": True, "requires_paid_account": True,
      "expected_fields": _EXPECTED_FULL,
      "scrape_url_template": "", "notes": ""},
    {"slug": "homeadvisor-landscape", "name": "HomeAdvisor — Landscaping",
      "category": "industry_landscape",
      "submission_url": "https://www.homeadvisor.com/r/",
      "homepage_url":   "https://www.homeadvisor.com/",
      "priority": 3, "requires_manual": True, "requires_paid_account": True,
      "expected_fields": _EXPECTED_STD,
      "scrape_url_template": "", "notes": "Same portal as Angi."},
    {"slug": "lawnstarter-pro", "name": "LawnStarter Pro Network",
      "category": "industry_landscape",
      "submission_url": "https://www.lawnstarter.com/pro",
      "homepage_url":   "https://www.lawnstarter.com/",
      "priority": 4, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_STD,
      "scrape_url_template": "", "notes": ""},
    {"slug": "greenpal", "name": "GreenPal",
      "category": "industry_landscape",
      "submission_url": "https://www.yourgreenpal.com/get-started",
      "homepage_url":   "https://www.yourgreenpal.com/",
      "priority": 4, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_STD,
      "scrape_url_template": "", "notes": ""},
    {"slug": "homeguide-landscape", "name": "HomeGuide — Landscaping",
      "category": "industry_landscape",
      "submission_url": "https://homeguide.com/pros/join",
      "homepage_url":   "https://homeguide.com/",
      "priority": 4, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_STD,
      "scrape_url_template": "", "notes": ""},
    {"slug": "houzz-landscape-pro", "name": "Houzz — Landscape Professionals",
      "category": "industry_landscape",
      "submission_url": "https://www.houzz.com/professionals/join",
      "homepage_url":   "https://www.houzz.com/",
      "priority": 3, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_FULL,
      "scrape_url_template": "", "notes": ""},
    {"slug": "nala-landscape", "name": "National Association of Landscape Professionals",
      "category": "industry_landscape",
      "submission_url": "https://www.landscapeprofessionals.org/join",
      "homepage_url":   "https://www.landscapeprofessionals.org/",
      "priority": 4, "requires_manual": True, "requires_paid_account": True,
      "expected_fields": _EXPECTED_STD,
      "scrape_url_template": "", "notes": "Trade association; membership fee."},
    {"slug": "porch-landscape", "name": "Porch — Landscaping",
      "category": "industry_landscape",
      "submission_url": "https://porch.com/pro/signup",
      "homepage_url":   "https://porch.com/",
      "priority": 4, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_STD,
      "scrape_url_template": "", "notes": ""},

    # ── Wholesale data aggregators ────────────────────────────────────
    {"slug": "data-axle", "name": "Data Axle (Infogroup)",
      "category": "aggregator",
      "submission_url": "https://www.data-axle.com/business-listings/",
      "homepage_url":   "https://www.data-axle.com/",
      "priority": 2, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_CORE,
      "scrape_url_template": "", "notes": "Feeds many downstream sites."},
    {"slug": "neustar-localeze", "name": "Neustar Localeze",
      "category": "aggregator",
      "submission_url": "https://www.neustarlocaleze.biz/",
      "homepage_url":   "https://www.neustarlocaleze.biz/",
      "priority": 2, "requires_manual": True, "requires_paid_account": True,
      "expected_fields": _EXPECTED_CORE,
      "scrape_url_template": "", "notes": "Paid; broad downstream distribution."},
    {"slug": "factual-foursquare", "name": "Foursquare Data / Factual",
      "category": "aggregator",
      "submission_url": "https://enterprise.foursquare.com/products/data",
      "homepage_url":   "https://enterprise.foursquare.com/",
      "priority": 3, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_CORE,
      "scrape_url_template": "", "notes": "Powers Apple Maps + Snapchat + others."},
    {"slug": "acxiom", "name": "Acxiom (LiveRamp) Business Records",
      "category": "aggregator",
      "submission_url": "https://www.acxiom.com/",
      "homepage_url":   "https://www.acxiom.com/",
      "priority": 4, "requires_manual": True, "requires_paid_account": True,
      "expected_fields": _EXPECTED_CORE,
      "scrape_url_template": "", "notes": ""},

    # ── Review-focused sites ──────────────────────────────────────────
    {"slug": "trustpilot", "name": "Trustpilot",
      "category": "review",
      "submission_url": "https://business.trustpilot.com/signup",
      "homepage_url":   "https://www.trustpilot.com/",
      "priority": 2, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_STD,
      "scrape_url_template": "https://www.trustpilot.com/review/{website_domain}",
      "notes": ""},
    {"slug": "sitejabber", "name": "Sitejabber",
      "category": "review",
      "submission_url": "https://www.sitejabber.com/business/signup",
      "homepage_url":   "https://www.sitejabber.com/",
      "priority": 4, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_CORE,
      "scrape_url_template": "", "notes": ""},
    {"slug": "consumeraffairs", "name": "ConsumerAffairs",
      "category": "review",
      "submission_url": "https://www.consumeraffairs.com/for-brands",
      "homepage_url":   "https://www.consumeraffairs.com/",
      "priority": 4, "requires_manual": True, "requires_paid_account": True,
      "expected_fields": _EXPECTED_STD,
      "scrape_url_template": "", "notes": ""},
    {"slug": "reviews-io", "name": "Reviews.io",
      "category": "review",
      "submission_url": "https://www.reviews.io/",
      "homepage_url":   "https://www.reviews.io/",
      "priority": 5, "requires_manual": True, "requires_paid_account": True,
      "expected_fields": _EXPECTED_CORE,
      "scrape_url_template": "", "notes": ""},
    {"slug": "bark", "name": "Bark.com",
      "category": "review",
      "submission_url": "https://www.bark.com/en/us/pros/",
      "homepage_url":   "https://www.bark.com/",
      "priority": 4, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_STD,
      "scrape_url_template": "", "notes": ""},

    # ── Local / community ─────────────────────────────────────────────
    {"slug": "nextdoor-business", "name": "Nextdoor Business",
      "category": "local",
      "submission_url": "https://business.nextdoor.com/",
      "homepage_url":   "https://nextdoor.com/",
      "priority": 2, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_STD,
      "scrape_url_template": "", "notes": "Great for hyper-local pool + landscape."},
    {"slug": "alignable", "name": "Alignable",
      "category": "local",
      "submission_url": "https://www.alignable.com/join",
      "homepage_url":   "https://www.alignable.com/",
      "priority": 3, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_STD,
      "scrape_url_template": "", "notes": ""},
    {"slug": "local-chamber", "name": "Local Chamber of Commerce",
      "category": "local",
      "submission_url": "",
      "homepage_url":   "https://www.uschamber.com/co/chambers",
      "priority": 3, "requires_manual": True, "requires_paid_account": True,
      "expected_fields": _EXPECTED_STD,
      "scrape_url_template": "", "notes": "Placeholder — actual URL depends on city."},
    {"slug": "meetup-org", "name": "Meetup Business",
      "category": "local",
      "submission_url": "https://www.meetup.com/pro/",
      "homepage_url":   "https://www.meetup.com/",
      "priority": 5, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_CORE,
      "scrape_url_template": "", "notes": "Only relevant if you run community events."},

    # ── Social / discovery ────────────────────────────────────────────
    {"slug": "instagram-business", "name": "Instagram Business Profile",
      "category": "social",
      "submission_url": "https://help.instagram.com/502981923235522",
      "homepage_url":   "https://www.instagram.com/",
      "priority": 2, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_CORE + ["description", "photos"],
      "scrape_url_template": "", "notes": ""},
    {"slug": "linkedin-company", "name": "LinkedIn Company Page",
      "category": "social",
      "submission_url": "https://www.linkedin.com/company/setup/new/",
      "homepage_url":   "https://www.linkedin.com/",
      "priority": 3, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_STD,
      "scrape_url_template": "", "notes": ""},
    {"slug": "tiktok-business", "name": "TikTok Business Account",
      "category": "social",
      "submission_url": "https://ads.tiktok.com/business/",
      "homepage_url":   "https://www.tiktok.com/",
      "priority": 4, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_CORE + ["description"],
      "scrape_url_template": "", "notes": ""},
    {"slug": "youtube-brand", "name": "YouTube Brand Channel",
      "category": "social",
      "submission_url": "https://support.google.com/youtube/answer/1646861",
      "homepage_url":   "https://www.youtube.com/",
      "priority": 4, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_CORE + ["description"],
      "scrape_url_template": "", "notes": ""},
    {"slug": "pinterest-business", "name": "Pinterest Business",
      "category": "social",
      "submission_url": "https://business.pinterest.com/",
      "homepage_url":   "https://www.pinterest.com/",
      "priority": 4, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_CORE + ["description"],
      "scrape_url_template": "", "notes": ""},
    {"slug": "twitter-x-business", "name": "X (Twitter) Business Profile",
      "category": "social",
      "submission_url": "https://business.x.com/",
      "homepage_url":   "https://x.com/",
      "priority": 4, "requires_manual": True, "requires_paid_account": False,
      "expected_fields": _EXPECTED_CORE + ["description"],
      "scrape_url_template": "", "notes": ""},
]


def _validate_catalog() -> None:
    """Startup-time invariant check — fail loudly if the seed drifts."""
    assert len(CATALOG) == 60, (
        f"CATALOG must define exactly 60 directories (found {len(CATALOG)}). "
        "Update DIRECTORY_TOTAL in tests if this changes."
    )
    seen: set = set()
    for row in CATALOG:
        assert row["slug"] not in seen, f"duplicate slug: {row['slug']}"
        seen.add(row["slug"])
        for k in ("slug", "name", "category", "priority", "expected_fields"):
            assert row.get(k) not in (None, ""), \
                f"missing {k!r} on {row.get('slug')}"
        assert row["priority"] in (1, 2, 3, 4, 5), \
            f"priority out of range on {row['slug']}"


_validate_catalog()

DIRECTORY_TOTAL = len(CATALOG)


async def ensure_seeded() -> Dict[str, Any]:
    """Idempotent seed. Upserts by ``slug``; leaves any tenant edits
    alone (there aren't any — this collection is global).

    Returns a summary the caller can log.
    """
    inserted = 0
    updated = 0
    now = now_iso()
    for row in CATALOG:
        base = {**row,
                 "active": True,
                 "updated_at": now}
        # ``id`` is stable across re-seeds. Never overwrite an existing
        # id — that would break references from ``directory_submissions``.
        existing = await db.directory_definitions.find_one(
            {"slug": row["slug"]}, {"_id": 0, "id": 1})
        if existing:
            await db.directory_definitions.update_one(
                {"slug": row["slug"]},
                {"$set": base})
            updated += 1
        else:
            base["id"] = new_id()
            base["created_at"] = now
            await db.directory_definitions.insert_one(base)
            inserted += 1
    logger.info(
        f"[directories] catalogue seeded — inserted={inserted}, "
        f"refreshed={updated}, total_active={DIRECTORY_TOTAL}"
    )
    return {"inserted": inserted, "updated": updated, "total": DIRECTORY_TOTAL}
