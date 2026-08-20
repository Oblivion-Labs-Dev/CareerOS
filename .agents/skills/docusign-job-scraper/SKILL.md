---
name: docusign-job-scraper
description: Scrape and retrieve Senior Software Engineer (and general engineering) job listings, Job IDs, direct links, and locations from DocuSign careers, with built-in filtering for United States roles.
---

# DocuSign Job Scraper Skill

This skill allows agents to fetch, scrape, and format Senior Software Engineer job listings from DocuSign's official career portal (`careers.docusign.com`).

## Scraped Active US Senior Software Engineer Jobs

Below is the list of active **Senior Software Engineer** job openings at DocuSign located in the **United States**:

| Job Title | Job ID | Job Link | Location |
| :--- | :--- | :--- | :--- |
| **Senior Software Engineer** | `29452` | [View Job](https://careers.docusign.com/careers-home/jobs/29452?lang=en-us&previousLocale=en-US) | San Francisco, California, United States |
| **Senior Software Engineer** | `29518` | [View Job](https://careers.docusign.com/careers-home/jobs/29518?lang=en-us&previousLocale=en-US) | Seattle, Washington, United States |
| **Sr. Software Engineer** | `29084` | [View Job](https://careers.docusign.com/careers-home/jobs/29084?lang=en-us&previousLocale=en-US) | San Francisco, California, United States |
| **Senior Software Engineer** | `29516` | [View Job](https://careers.docusign.com/careers-home/jobs/29516?lang=en-us&previousLocale=en-US) | Seattle, Washington, United States |
| **Senior Software Engineer** | `29478` | [View Job](https://careers.docusign.com/careers-home/jobs/29478?lang=en-us&previousLocale=en-US) | Seattle, Washington, United States |
| **Senior Software Engineer** | `29543` | [View Job](https://careers.docusign.com/careers-home/jobs/29543?lang=en-us&previousLocale=en-US) | Seattle, Washington, United States |
| **Senior Software Engineer** | `28988` | [View Job](https://careers.docusign.com/careers-home/jobs/28988?lang=en-us&previousLocale=en-US) | Seattle, Washington, United States |
| **Senior Software Engineer - New Revenue** | `29733` | [View Job](https://careers.docusign.com/careers-home/jobs/29733?lang=en-us&previousLocale=en-US) | Multiple (US Flexible/Remote) |
| **Senior Software Engineer** | `29945` | [View Job](https://careers.docusign.com/careers-home/jobs/29945?lang=en-us&previousLocale=en-US) | Multiple (US Flexible/Remote) |
| **Senior Software Engineer** | `29638` | [View Job](https://careers.docusign.com/careers-home/jobs/29638?lang=en-us&previousLocale=en-US) | Multiple (US Flexible/Remote) |

## How to Re-Scrape DocuSign Jobs

To update or re-scrape job listings dynamically:

1. Launch a browser agent or run headless automation to visit `https://careers.docusign.com/company/careers`.
2. Search for the keyword `Senior Software Engineer`.
3. Extract elements matching `.job-title-link` and parent container details.
4. Filter out any locations that do not contain `United States` or `US` or `San Francisco` / `Seattle`.
