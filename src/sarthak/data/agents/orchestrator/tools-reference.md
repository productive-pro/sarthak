## Tool Reference

### Activity
- `query_activity(days, limit)` — app-time digest stats (no raw rows)
- `get_summary(date_str)` — AI daily summary text
- `get_tips(limit)` / `save_tip(tip)` — learning tip CRUD

### Shell & System
- `run_shell(command)` — safe read-only shell (disabled if allow_shell=False)
- `service_status()` / `restart_service(service)` — systemd/service ops

### Skills (user knowledge snippets)
- `list_skills_tool()` — show all saved skills
- `read_skill_tool(name)` — load full skill content
- `save_skill_tool(name, description, content, tags)` — persist a skill
- `delete_skill_tool(name)` — remove a skill

### Spaces (learning)
- `spaces_context(space_dir)` — **call first** for any learning request
- `spaces_session(space_dir, space_type)` — run a learning session
- `spaces_status(space_dir)` — show mastery progress
- `spaces_quick(space_dir)` — 5-minute micro-task
- `spaces_evaluate(concept, submission, space_dir)` — grade submission
- `spaces_list()` — list all registered spaces
- `spaces_init(space_dir, space_type, ...)` — create new space
- `spaces_setup(space_dir)` — scan tools, reshape workspace

### RAG & Workspace
- `spaces_rag_index(space_dir, full)` — index workspace files
- `spaces_rag_search(query, space_dir, top_k)` — semantic search
- `workspace_qa(question, space_dir)` — answer questions about workspace data
- `workspace_analyse(space_dir)` — refresh Optimal_Learn.md
