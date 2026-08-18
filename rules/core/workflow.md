# Workflow rules

## Fetching what the user points at

`WebFetch` reads public HTML/JSON pages, nothing else. So:

- **A remote binary — PDF, archive, office file — is not fetchable.** Ask the user to download it
  and share the file, or to paste the content.
- **A local file is a `Read`, never a fetch** — including PDFs, which `Read` renders page by page.
- **A failed fetch is a question, not a retry.** Do not go hunting for alternate URLs; ask.
