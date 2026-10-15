# 2-minute video script

Aim for about 1:45. Record your screen with the app open; your face in a corner is a nice touch.

---

**0:00–0:20 — The problem** *(screen: empty start page)*

> "SaaSquatch is great at producing lead lists. But the real cost comes after: someone opens every website, hunts for the owner's email, wonders if it works, and decides who's worth a call. I built LeadLens to do that part automatically: it turns a list of websites into verified, ranked leads, and explains every score."

**0:20–0:50 — Run it** *(click "Try it with demo companies")*

> "I'll paste a messy list, the kind you get from combining a CRM export with a scraper. It has a duplicate, a row that isn't a website, a dead site, and a site that blocks bots."
>
> *(results appear)* "In about a second it read every site, found the owners' direct emails, including one written as 'jane at domain dot com' to hide it from scrapers, checked each email's domain can actually receive mail, removed the duplicate, and ranked everything."

**0:50–1:15 — Explainability** *(click the top lead to open the drawer)*

> "Every score is itemized, so a rep can trust it. Each segment of this bar is a reason. And there's always a concrete next step: email Mike Delgado, the owner, directly."

**1:15–1:35 — Two lenses** *(switch between "Sales outreach" and "Acquisition targets")*

> "Caprae uses lead data both to sell and to buy businesses. Switching to the acquisition lens re-ranks instantly, without re-scraping: established, owner-run businesses with an outdated web presence rise to the top, because that's where post-acquisition value creation lives."

**1:35–1:50 — Into the workflow** *(tick "Verified email only", click Export CSV, show the file)*

> "Filter to verified emails and export a CSV with HubSpot and Salesforce column names, ready to import."

**1:50–2:00 — Architecture** *(show README architecture section)*

> "Under the hood: FastAPI with async httpx, SQLite with page and MX caching, robots.txt and rate limits built in, 15 automated tests, deployed as a Docker container on Render. Next I'd add LLM-written openers and direct CRM sync. Thanks!"
