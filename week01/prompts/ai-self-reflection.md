# AI Self-Reflection

## Exercise 1

**no review:**
```
Write a Python function `parse_duration(text)` that converts a human-readable duration string into total seconds.

Requirements:
- Accept inputs like `"2h 30m"`, `"45m"`, `"1h 15m 30s"`, `"90s"`.
- Supported units: `h` (hours), `m` (minutes), `s` (seconds). Units may appear in any order; whitespace is optional.
- Return an `int` number of seconds.
- Raise `ValueError` with a clear message for invalid input (unknown units, negative numbers, empty string, duplicate units).
- Include a docstring with 3 example usages.
- Keep the function body under 20 lines.
```

**with review:**
```
Write a Python function `parse_duration(text)` that converts a human-readable duration string into total seconds.

Requirements:
- Accept inputs like `"2h 30m"`, `"45m"`, `"1h 15m 30s"`, `"90s"`.
- Supported units: `h` (hours), `m` (minutes), `s` (seconds). Units may appear in any order; whitespace is optional.
- Return an `int` number of seconds.
- Raise `ValueError` with a clear message for invalid input (unknown units, negative numbers, empty string, duplicate units).
- Include a docstring with 3 example usages.
- Keep the function body under 20 lines.

After producing your answer, review it:
- Are there factual mistakes?
- Did you follow all my constraints?
- Are there edge cases you missed?
- Is the format and tone correct?

If you find issues, fix them and produce a final, corrected version.
```


## Exercise 2

```
Step 1 — Initial Answer:
Produce your best answer to [task]. Mark this section "INITIAL ANSWER".

Step 2 — Critique:
Now critically review your initial answer. List at least 3 specific issues, 
weaknesses, or things you'd improve. Mark this section "CRITIQUE".

Step 3 — Final:
Produce a revised final answer. Mark this section "FINAL".

Use clear section headers between the three.
```

## Exercise 3

```
Task: [task]

After producing your answer, switch roles. You are now a strict senior 
reviewer who is skeptical of the answer. Find at least 3 things the 
answer:
- gets factually wrong, or
- oversimplifies, or
- fails to address from the original request.

Then, based on this critique, produce a revised answer.
```
