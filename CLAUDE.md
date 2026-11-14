# CLAUDE.md

Project: LLM-Grounded Semantic Object Search in a Known Floorplan (CSC 591 Advanced Robotics).

## Standing rules

- Never run commands, and never commit or push. Only create and edit files. Give me exact commands to run and wait for the output.
- docs/DESIGN_DECISIONS.md is the source of truth for design choices. Append an entry (ID, date, status, decision, why, alternatives) for every design choice you make, and never change an Agreed decision without asking me.
- src/lang_grounding must stay free of ROS imports. ROS code lives in ros/ as thin wrappers.
- API keys come from environment variables only. Never commit secrets.
- The model name is a config setting, never hardcoded.
- Few-shot prompt examples must not overlap the E1 test commands.
- Write tests with every feature, and give me the command to run them. Do not claim a task is done until I have pasted passing results.
- Do only what the current prompt asks. Flag anything extra instead of adding it.

## Layout

- src/lang_grounding/: pure Python package (no ROS)
- tests/: pytest tests
- docs/: design docs (DESIGN_DECISIONS.md)
- data/: scene graph and other data files
- configs/: configuration files
- ros/: ROS 2 packages (house_sim exists: simulation, Nav2, objects). ROS wrappers around lang_grounding go here as thin packages.
