Now, from the same meeting-transcript.txt, extract a backlog suitable
for Jira. Rules:

- Group work into 4–7 EPICS covering distinct feature areas or
  workstreams (e.g. Inventory, Sales Tracking, Reporting, UI/UX,
  Infrastructure).
- Each epic: title, 1–2 sentence description, list of tasks.
- Each task: title in imperative form, 1–3 sentence description,
  owner ("Joanne" | "Greg" | "Mike" | "Unassigned"),
  due_date (ISO 8601 or null), priority ("High" | "Medium" | "Low").
- Do NOT invent tasks that were not discussed. Unresolved topics go
  into "open_questions".

Return ONLY valid JSON, no prose, no code fences, no comments.
Schema:

{
"epics": [
{
"title": "...",
"description": "...",
"tasks": [
{"title": "...", "description": "...", "owner": "...",
"due_date": "YYYY-MM-DD" | null, "priority": "..."}
]
}
],
"open_questions": ["..."]
}

Write the JSON to backlog.json.