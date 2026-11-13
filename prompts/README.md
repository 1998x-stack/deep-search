# Prompt pack

`master.md` summarizes the end-to-end decision process for the agent host.
`factory/prompts.py` contains **executable** planner, evidence, critic and synthesis role instructions sent to the model.

The algorithm is controlled by real Python code, not by a prompt-only promise. Prompt roles are logical tasks; they do not imply parallel worker processes. Search and model provider calls are documented in `docs/API.md`.

