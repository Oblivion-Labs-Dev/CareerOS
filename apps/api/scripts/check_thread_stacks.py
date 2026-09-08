import sys
import threading
import traceback
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.application_assistant.browser_runner import _playwright_thread, _playwright_loop

print("Playwright thread:", _playwright_thread)
print("Is alive:", _playwright_thread.is_alive() if _playwright_thread else "None")
print("Playwright loop:", _playwright_loop)

# Notice this runs in a separate process, so _playwright_thread won't show the server's thread unless inspected within the server process.
