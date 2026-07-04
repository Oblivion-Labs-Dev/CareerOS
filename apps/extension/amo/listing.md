# CareerOS ApplyPilot — Firefox Add-ons (AMO) Listing

Use this content when submitting at https://addons.mozilla.org/developers/

## Add-on name
CareerOS ApplyPilot

## Summary (max ~250 chars)
Autofill job applications, attach your resume, learn unknown ATS fields, and sync applications with CareerOS.

## Description

ApplyPilot is the CareerOS browser extension for job seekers.

**Features**
- Detect job application forms on major ATS sites
- Autofill profile fields (name, email, phone, LinkedIn, work authorization, etc.)
- Attach resume and cover letter files
- Learn unknown screening questions for future applications
- Save jobs and track application status
- Sync profile and applications with your CareerOS backend

**Privacy**
ApplyPilot stores your profile and application data locally in the browser and syncs with your configured CareerOS API. No third-party analytics SDK is bundled.

**Requirements**
- A running CareerOS API (default: localhost:8000 for development)
- Configure your profile in the extension popup or CareerOS dashboard

## Extension ID
`career-os@applypilot.dev`

## Categories
Other OR Privacy & Security → Job search tools

## Support email
(Your support email)

## Privacy policy URL
https://YOUR-DOMAIN/privacy/applypilot

(For local AMO review, use your deployed CareerOS URL or GitHub Pages.)

## License
Proprietary — adjust before publish

## Notes for reviewers
- Connects to user-configured CareerOS API at localhost:8000 in development
- Host permission `<all_urls>` required to scan job application forms on employer sites
- MV3 service worker background script
