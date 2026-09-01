"""Unit tests reproducing Greenhouse form DOM state and verifying autopilot fill & file handling."""

import os
import pytest
from playwright.async_api import async_playwright
from app.services.application_assistant.playwright_autopilot_executor import _fill_standard_and_react_fields, _extract_dom_form_state
from app.services.application_assistant.field_fill_engine import fill_field

# Exact DOM snapshot replicating Greenhouse / Anduril forms with custom questions and file uploads
GREENHOUSE_SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head><title>Anduril - Software Engineer Application</title></head>
<body>
<form id="application_form">
  <div class="field">
    <label for="first_name">First Name *</label>
    <input type="text" id="first_name" name="job_application[first_name]" required />
  </div>
  <div class="field">
    <label for="last_name">Last Name *</label>
    <input type="text" id="last_name" name="job_application[last_name]" required />
  </div>
  <div class="field">
    <label for="email">Email *</label>
    <input type="email" id="email" name="job_application[email]" required />
  </div>
  <div class="field">
    <label for="phone">Phone *</label>
    <input type="tel" id="phone" name="job_application[phone]" required />
  </div>
  <div class="field">
    <label for="resume">Resume/CV *</label>
    <input type="file" id="resume" name="job_application[resume]" required />
  </div>

  <!-- Optional Cover Letter file input -->
  <div class="field">
    <label for="cover_letter">Cover Letter</label>
    <input type="file" class="visually-hidden" id="cover_letter" name="cover_letter" />
  </div>

  <!-- Screening Question 1: Local / Relocate (React Select) -->
  <div class="field custom-question">
    <label for="question_101">If you are not local to Colorado, are you willing to relocate? *</label>
    <div class="select__control">
      <input type="text" role="combobox" id="question_101" />
    </div>
    <div class="select__menu" style="display:none;">
      <div class="select__option" role="option">Select...</div>
      <div class="select__option" role="option">Yes</div>
      <div class="select__option" role="option">No</div>
    </div>
  </div>

  <!-- Screening Question 2: Academic Transcripts Upload (Optional file input with question_ ID) -->
  <div class="field custom-question">
    <label for="question_12409844007">If willing to share your transcripts, please upload them here.</label>
    <input type="file" class="visually-hidden" id="question_12409844007" />
  </div>

  <!-- Screening Question 3: Clearance Eligibility (React Select) -->
  <div class="field custom-question">
    <label for="question_102">CLEARANCE ELIGIBILITY - This position requires eligibility to obtain and maintain a U.S. security clearance. *</label>
    <div class="select__control">
      <input type="text" role="combobox" id="question_102" />
    </div>
    <div class="select__menu" style="display:none;">
      <div class="select__option" role="option">Select...</div>
      <div class="select__option" role="option">Yes, I am eligible</div>
      <div class="select__option" role="option">No</div>
    </div>
  </div>

  <!-- Screening Question 4: Export Controls (React Select) -->
  <div class="field custom-question">
    <label for="question_103">EXPORT CONTROLS - This position requires access to information and technology subject to U.S. export controls. *</label>
    <div class="select__control">
      <input type="text" role="combobox" id="question_103" />
    </div>
    <div class="select__menu" style="display:none;">
      <div class="select__option" role="option">Select...</div>
      <div class="select__option" role="option">U.S. Citizen / Lawful Permanent Resident</div>
      <div class="select__option" role="option">Other</div>
    </div>
  </div>

  <!-- Screening Question 5: Work Authorization (React Select) -->
  <div class="field custom-question">
    <label for="question_104">U.S. WORK AUTHORIZATION *</label>
    <div class="select__control">
      <input type="text" role="combobox" id="question_104" />
    </div>
    <div class="select__menu" style="display:none;">
      <div class="select__option" role="option">Select...</div>
      <div class="select__option" role="option">Yes</div>
      <div class="select__option" role="option">No</div>
    </div>
  </div>

  <!-- Screening Question 6: Sponsorship (React Select) -->
  <div class="field custom-question">
    <label for="question_105">Will you require sponsorship from Anduril for employment now or in the future? *</label>
    <div class="select__control">
      <input type="text" role="combobox" id="question_105" />
    </div>
    <div class="select__menu" style="display:none;">
      <div class="select__option" role="option">Select...</div>
      <div class="select__option" role="option">Yes</div>
      <div class="select__option" role="option">No</div>
    </div>
  </div>

  <!-- Website / Portfolio URL -->
  <div class="field">
    <label for="website">Website</label>
    <input type="text" id="website" name="website" />
  </div>

  <!-- Hidden reCAPTCHA response textarea -->
  <textarea name="g-recaptcha-response" class="g-recaptcha-response" id="g-recaptcha-response-100000" style="display:none;"></textarea>

  <button type="submit" id="submit_app">Submit application</button>
</form>

<script>
// Simulate React Select opening dropdown when control is clicked
document.querySelectorAll('.select__control').forEach(ctrl => {
  ctrl.addEventListener('click', (e) => {
    const parent = ctrl.closest('.custom-question');
    const menu = parent.querySelector('.select__menu');
    if (menu) menu.style.display = 'block';
  });
});

document.querySelectorAll('.select__option').forEach(opt => {
  opt.addEventListener('click', (e) => {
    const parent = opt.closest('.custom-question');
    const input = parent.querySelector('input[role="combobox"]');
    if (input) input.value = opt.innerText;
    const menu = parent.querySelector('.select__menu');
    if (menu) menu.style.display = 'none';
  });
});
</script>
</body>
</html>
"""

import anyio

@pytest.mark.anyio
async def test_greenhouse_anduril_form_filling_and_file_safety():
    """Verify that file inputs are never filled with text and all custom comboboxes are selected."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.set_content(GREENHOUSE_SAMPLE_HTML)

        # Create a dummy resume file for attachment test
        tmp_resume = "test_sample_resume.pdf"
        with open(tmp_resume, "wb") as f:
            f.write(b"%PDF-1.4 dummy content")

        profile = {
            "firstName": "Akshay",
            "lastName": "Borse",
            "email": "amsborse@gmail.com",
            "phone": "425-336-9852",
            "location": "Auburn, WA",
            "portfolio": "https://amsborse.github.io/resume",
            "workAuthorization": "Yes",
            "sponsorship": "No",
        }

        # 1. Run standard and custom filling
        filled = await _fill_standard_and_react_fields(
            page=page,
            profile=profile,
            answer_lib=[],
            company="Anduril",
            title="Software Engineer",
            resume_file=tmp_resume,
        )

        assert filled.get("First Name") == "Akshay"
        assert filled.get("Email") == "amsborse@gmail.com"
        assert filled.get("Resume") == "test_sample_resume.pdf"

        # 2. Verify file safety in field_fill_engine: attempt to pass text to a file input
        file_action = {
            "selector": "#question_12409844007",
            "selectorHint": "#question_12409844007",
            "fieldLabel": "Transcripts",
            "fieldType": "text", # Misclassified on purpose
            "fileName": "test_sample_resume.pdf",
        }
        
        # Must not raise "Locator.fill: Error: Input of type 'file' cannot be filled"
        ok, reason = await fill_field(page, file_action, tmp_resume, profile=profile)
        assert ok is True
        assert reason in ("file", "file_direct")

        # 3. Verify DOM state extraction ignores reCAPTCHA
        fields, errors = await _extract_dom_form_state(page)
        recaptcha_fields = [f for f in fields if "recaptcha" in f.get("id", "").lower()]
        assert len(recaptcha_fields) == 0, "reCAPTCHA textarea must be filtered out"

        # Cleanup
        if os.path.exists(tmp_resume):
            os.remove(tmp_resume)

        await browser.close()
