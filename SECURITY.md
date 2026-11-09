# Security

Do not disclose credentials, original private documents, or SQLite databases in public GitHub issues. Use GitHub private vulnerability reporting when available.

Trust boundary: this CLI is for an authenticated local/Sprite operator and an authorized inference client. There is no public API, multi-tenant authorization, user isolation, or unattended ChatGPT execution.

Persistent state includes original source text, native prompts, and model responses. Protect backups and logs and manage retention explicitly. Treat source text and extracted text as untrusted data.
