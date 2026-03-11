-- PostgreSQL named queries for ActivityRepository
-- Uses $N positional parameters (asyncpg style)

-- :name insert_activity
INSERT INTO user_activity
    (activity_type, space_dir, concept_id, concept_title,
     session_id, content_text, media_path, metadata)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
RETURNING id

-- :name summary
SELECT activity_type, COUNT(*) AS cnt
FROM user_activity
WHERE space_dir = $1 AND ts >= $2
GROUP BY activity_type

-- :name failed_code_concepts
SELECT concept_title, COUNT(*) AS fails
FROM user_activity
WHERE space_dir = $1
  AND activity_type = 'code_run'
  AND ts >= $2
  AND (metadata->>'success')::boolean = false
  AND concept_title != ''
GROUP BY concept_title
HAVING COUNT(*) >= $3

-- :name concepts_touched
SELECT DISTINCT concept_title
FROM user_activity
WHERE space_dir = $1 AND concept_title != '' AND ts >= $2
ORDER BY MAX(ts) DESC

-- :name recent_media_notes
SELECT * FROM user_activity
WHERE space_dir = $1
  AND activity_type IN ('audio_note','video_note')
  AND ts >= $2
ORDER BY ts DESC
LIMIT 50

-- :name insert_message
INSERT INTO chat_history (session_id, role, content) VALUES ($1, $2, $3)

-- :name get_history
SELECT session_id, ts, role, content
FROM chat_history
WHERE session_id = $1
ORDER BY ts ASC
LIMIT $2

-- :name get_sessions
SELECT session_id, MAX(ts) AS last_ts, COUNT(*) AS msg_count
FROM chat_history
GROUP BY session_id
ORDER BY last_ts DESC
LIMIT $1

-- :name latest_session_id
SELECT session_id FROM chat_history ORDER BY ts DESC LIMIT 1
