"""Mounted only for local process-death qualification; absent from runtime images."""

import time
from pathlib import Path
from app.main import app as app
from app.llm import ScriptedProvider
from app.db import connection

original = ScriptedProvider.interpret


def paused(self, text, state):
    if text.startswith("qualification-pause"):
        with connection() as conn:
            conn.execute(
                "INSERT INTO pilot_audit(event,object_id) VALUES('qualification_attempt',%s)",
                (state.problem_id,),
            )
        Path("/tmp/qualification-entered").write_text("inference in flight")
        time.sleep(30)
    return original(self, text, state)


ScriptedProvider.interpret = paused
