from pathlib import Path

target_file = Path("app/services/application_assistant/playwright_autopilot_executor.py")
content = target_file.read_text(encoding="utf-8")

old_code = '''    # Fill Location (City) if requested
    loc_input = page.locator('input[id*="candidate_location" i], input[id*="location" i], input[name*="location" i]').first
    if await loc_input.count() > 0 and await loc_input.is_visible():
        city_val = profile.get("location") or "Auburn, WA"
        if city_val.strip().lower() in ("akshay", "akshay borse", "none", ""):
            city_val = "Auburn, WA"
        try:
            await loc_input.fill(city_val)
            filled["Location"] = city_val
            filled_ids["Location"] = await loc_input.get_attribute("id") or ""
            await asyncio.sleep(0.3)
            # Many ATS location fields are a Google-Places-style autocomplete: typed
            # text alone doesn't satisfy the required field until a suggestion is
            # actually clicked (or the highlighted one confirmed). Match generically
            # against the parts of city_val — a hardcoded "Auburn, WA"-only match
            # left every other city (i.e. real production usage) unfillable.
            suggestions = page.locator('.location-suggestion, [role="option"], .pac-item, li[class*="suggestion"]')
            sug_count = await suggestions.count()
            city_parts = [p.strip().lower() for p in city_val.split(",") if p.strip()]
            clicked = False
            if sug_count > 0:
                # Prefer a suggestion matching ALL parts (city AND state) over one
                # matching only the city name — "Auburn, WA" was previously matched
                # with a plain `any()`, so the first "Auburn, <wrong state>" in the
                # list (there are several real US cities named Auburn) won over the
                # correct one further down. Fall back to a partial/first-visible
                # match only when no full match exists, so the field still gets
                # something rather than being left uncommitted.
                first_visible_el = None
                partial_match_el = None
                full_match_el = None
                for s_idx in range(min(sug_count, 8)):
                    s_el = suggestions.nth(s_idx)
                    if not await s_el.is_visible():
                        continue
                    s_text = (await s_el.inner_text()).lower()
                    if first_visible_el is None:
                        first_visible_el = s_el
                    if partial_match_el is None and any(part and part in s_text for part in city_parts):
                        partial_match_el = s_el
                    if full_match_el is None and city_parts and all(part in s_text for part in city_parts):
                        full_match_el = s_el
                        break
                best_el = full_match_el or partial_match_el or first_visible_el
                if best_el is not None:
                    await best_el.click(force=True)
                    clicked = True
            if not clicked and sug_count > 0:
                # A suggestion list rendered but nothing matched by text — the
                # highlighted/first option is still far better than leaving the
                # required field uncommitted.
                try:
                    await page.keyboard.press("ArrowDown")
                    await page.keyboard.press("Enter")
                except Exception:
                    pass
        except Exception:
            pass'''

new_code = '''    # Fill Location (City) if requested
    loc_input = page.locator('input[id*="candidate-location" i], input[id*="candidate_location" i], input[id*="location" i], input[name*="location" i]').first
    if await loc_input.count() > 0 and await loc_input.is_visible():
        city_full = profile.get("location") or "Seattle, WA"
        if city_full.strip().lower() in ("akshay", "akshay borse", "none", ""):
            city_full = "Seattle, WA"
        city_search = (profile.get("city") or city_full.split(",")[0]).strip() or "Seattle"
        try:
            await loc_input.fill(city_search)
            filled["Location"] = city_full
            filled_ids["Location"] = await loc_input.get_attribute("id") or ""
            await asyncio.sleep(0.8)
            # Scoped selector for location autocomplete suggestions to avoid matching
            # country or dial-code dropdown menus elsewhere on the page
            suggestions = page.locator(
                'div[id*="candidate-location-listbox"] [role="option"], '
                'div[id*="candidate-location-option"], '
                'div[id*="candidate_location"] [role="option"], '
                'div[class*="select__menu"] div[class*="option"], '
                'div[class*="select__option"], '
                '.location-suggestion, .pac-item, li[class*="suggestion"]'
            )
            sug_count = await suggestions.count()
            city_parts = [p.strip().lower() for p in city_full.split(",") if p.strip()]
            clicked = False
            if sug_count > 0:
                first_visible_el = None
                partial_match_el = None
                full_match_el = None
                for s_idx in range(min(sug_count, 12)):
                    s_el = suggestions.nth(s_idx)
                    if not await s_el.is_visible():
                        continue
                    s_text = (await s_el.inner_text()).lower()
                    if first_visible_el is None:
                        first_visible_el = s_el
                    if partial_match_el is None and any(part and part in s_text for part in city_parts):
                        partial_match_el = s_el
                    if full_match_el is None and city_parts and all(part in s_text for part in city_parts):
                        full_match_el = s_el
                        break
                best_el = full_match_el or partial_match_el or first_visible_el
                if best_el is not None:
                    await best_el.click(force=True)
                    clicked = True
                    await asyncio.sleep(0.4)
            if not clicked:
                try:
                    await page.keyboard.press("ArrowDown")
                    await asyncio.sleep(0.1)
                    await page.keyboard.press("Enter")
                    await asyncio.sleep(0.3)
                except Exception:
                    pass
        except Exception:
            pass'''

normalized_content = content.replace("\r\n", "\n")
normalized_old = old_code.replace("\r\n", "\n")
normalized_new = new_code.replace("\r\n", "\n")

if normalized_old in normalized_content:
    updated = normalized_content.replace(normalized_old, normalized_new)
    target_file.write_text(updated, encoding="utf-8")
    print("SUCCESS: Patched playwright_autopilot_executor.py")
else:
    print("ERROR: old_code block not found in file")
