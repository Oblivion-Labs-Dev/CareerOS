import sys
sys.path.insert(0, 'apps/api')
from app.services.application_assistant.autopilot_runner import AutopilotRunner
runner = AutopilotRunner.get_instance()
print(f"_loop_task: {runner._loop_task}")
print(f"_loop_task done: {runner._loop_task.done() if runner._loop_task else 'None'}")
print(f"_stop_requested: {runner._stop_requested}")
print(f"_pause_requested: {runner._pause_requested}")