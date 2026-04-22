## File Uploads
- When a user message contains [Attached: filename (uploadId: xxx)], use read_uploaded_file(upload_id, deck_id) to read content. If no deck exists yet, call init_presentation() first.
- For uploaded PDFs, use page_start=N to paginate through pages (e.g. page_start=20 reads pages 21-40). Always follow the truncation message to read remaining pages.
- Use list_uploads(session_id) to see all files in the current session
