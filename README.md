# TV-character-chatbot

To refresh the frontend that Render serves from `static/`, run:

```bash
./build_static.sh
```

That script builds `ui/` and copies the output into `static/`.

Both servers now write chat turns to `eval_logs.db` by default for offline evaluation.
Disable it with `--no-eval-logging` or point it elsewhere with `--eval-log-db /path/to/eval_logs.db`.

To inspect recent records in the same shape as the previous logger:

```bash
sqlite3 eval_logs.db -header -column "SELECT log_id, character, substr(user_message,1,30) AS user_msg, substr(bot_response,1,50) AS bot_resp, round(rag_time_ms) AS rag_ms, round(llm_time_ms) AS llm_ms, round(total_time_ms) AS total_ms, created_at FROM eval_logs ORDER BY created_at DESC LIMIT 20;"
```
