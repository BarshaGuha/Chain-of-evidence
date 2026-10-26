# Examples: live runs on Zetaris + Meterless Nightshift + NVIDIA Nemotron

Each folder is one real investigation, copied from `logs/` with `python3 -m agent.save_example OOS-00X`:

| File | What it shows |
|---|---|
| `report.md` | The signed-off root-cause report, with the Meterless receipts table |
| `trace.jsonl` | Every message between the agents, in order: how the team reached its answer |
| `world_model.jsonl` | The Meterless World Model case board: every fact with its SQL and source, every hypothesis state (including rollbacks) |
| `receipts.jsonl` | One signed Meterless compute receipt per model call: which model handled each request, latency, tokens, signature |
