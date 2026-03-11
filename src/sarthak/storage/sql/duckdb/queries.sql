-- DuckDB named queries for ActivityRepository
-- Uses ? positional parameters (duckdb-api style)

-- :name insert_activity
INSERT INTO user_activity
    (id, activity_type, space_dir, concept_id, concept_title,
     session_id, content_text, media_path, metadata)
VALUES (nextval('user_activity_id_seq'),?,?,?,?,?,?,?,?)
RETURNING id

-- :name summary
SELECT activity_type, COUNT(*) AS cnt
FROM user_activity
WHERE space_dir = ? AND ts >= ?
GROUP BY activity_type

-- :name failed_code_concepts
SELECT concept_title, COUNT(*) AS fails
FROM user_activity
WHERE space_dir = ?
  AND activity_type = 'code_run'
  AND ts >= ?
  AND json_extract_string(metadata, '$.success') = 'false'
  AND concept_title != ''
GROUP BY concept_title
HAVING fails >= ?

-- :name concepts_touched
SELECT DISTINCT concept_title
FROM user_activity
WHERE space_dir = ? AND concept_title != '' AND ts >= ?
ORDER BY MAX(ts) DESC

-- :name recent_media_notes
SELECT * FROM user_activity
WHERE space_dir = ?
  AND activity_type IN ('audio_note','video_note')
  AND ts >= ?
ORDER BY ts DESC
LIMIT 50
