def application_list_priority(job: dict) -> float:
    """Match the application list's Senior/Washington ordering before pagination."""
    title = str(job.get("title") or "").lower()
    location = str(job.get("location") or "").lower()
    score = float(job.get("matchScore") or 0)
    above = any(k in title for k in ("staff", "principal", "distinguished", "fellow", "architect", "director", "head of", "vp ", "vice president"))
    senior = any(k in title for k in ("senior software engineer", "sr. software engineer", "sr software engineer", "senior swe"))
    if senior and not above:
        score += 40
    elif above:
        score -= 40
    elif "senior" in title and "software engineer" in title:
        score += 30
    elif "software engineer" in title or "software developer" in title:
        score += 10
    if any(k in location for k in ("seattle", "bellevue", "redmond", "kirkland", ", wa", "washington")):
        score += 25
    return score
