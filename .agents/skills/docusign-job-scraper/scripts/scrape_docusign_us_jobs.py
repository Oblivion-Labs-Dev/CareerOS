"""
DocuSign US Senior Software Engineer Job Scraper
"""
import json
import re
import urllib.request

def fetch_docusign_jobs(keyword="Senior Software Engineer"):
    url = "https://careers.docusign.com/company/careers"
    print(f"DocuSign Job portal: {url}")
    print(f"Keyword search: {keyword}")

if __name__ == "__main__":
    fetch_docusign_jobs()
