-- SQLite chat_history queries

-- :name insert_message
INSERT INTO chat_history (session_id, role, content) VALUES (?, ?, ?)

-- :name get_history
SELECT session_id, ts, role, content
FROM chat_history
WHERE session_id = ?
ORDER BY ts ASC
LIMIT ?

-- :name get_sessions
SELECT session_id, MAX(ts) AS last_ts, COUNT(*) AS msg_count
FROM chat_history
GROUP BY session_id
ORDER BY last_ts DESC
LIMIT ?

-- :name latest_session_id
SELECT session_id FROM chat_history ORDER BY ts DESC LIMIT 1
