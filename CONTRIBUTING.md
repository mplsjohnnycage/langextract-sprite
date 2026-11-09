# Contributing

This is an independent community extension of Google LangExtract.

Open an issue first when proposing an extension. Prefer complementary infrastructure rather than reimplementing upstream LangExtract behavior.

Write a failing test before changing behavior. Run `python -m pytest -q` and provide source-span evidence for new extraction features. Avoid logging private source texts and model prompts.

Do not commit tokens, private documents, databases, or private ChatGPT plugin installation URLs. Do not misrepresent source matching as verification of factual claims.

The `skills/` directory documents the active ChatGPT/Sprite reference workflow; files are not automatically registered as ChatGPT skills.
