-- SQLite named queries for ActivityRepository
-- Loaded by SQLiteActivityRepo via sql_loader.load_queries("sqlite", "queries_activity")
-- Each query section starts with:  -- :name <query_name>

-- :name insert_activity
INSERT INTO user_activity
    (activity_type, space_dir, concept_id, concept_title,
     session_id, content_text, media_path, metadata)
VALUES (?,?,?,?,?,?,?,?)

-- :name query_all
-- Caller supplies: cutoff_ts, limit
-- Dynamic filters (space_dir, activity_type, concept_title) are applied
-- in SQLiteActivityRepo.query() by building a minimal WHERE clause.
-- These named variants are kept for potential future use by other backends.
SELECT * FROM user_activity
WHERE ts >= ?
ORDER BY ts DESC
LIMIT ?

-- :name query_filtered_space
SELECT * FROM user_activity
WHERE ts >= ? AND space_dir = ?
ORDER BY ts DESC
LIMIT ?

-- :name query_filtered_type
SELECT * FROM user_activity
WHERE ts >= ? AND activity_type = ?
ORDER BY ts DESC
LIMIT ?

-- :name query_filtered_space_type
SELECT * FROM user_activity
WHERE ts >= ? AND space_dir = ? AND activity_type = ?
ORDER BY ts DESC
LIMIT ?

-- :name query_filtered_space_concept
SELECT * FROM user_activity
WHERE ts >= ? AND space_dir = ? AND concept_title = ?
ORDER BY ts DESC
LIMIT ?

-- :name query_filtered_space_type_concept
SELECT * FROM user_activity
WHERE ts >= ? AND space_dir = ? AND activity_type = ? AND concept_title = ?
ORDER BY ts DESC
LIMIT ?

-- :name summary
-- Uses SQLite native date arithmetic — no Python-side cutoff string needed.
-- Caller supplies: space_dir, days (integer)
SELECT activity_type, COUNT(*) AS cnt
FROM user_activity
WHERE space_dir = ?
  AND ts >= datetime('now', '-' || ? || ' days')
GROUP BY activity_type

-- :name failed_code_concepts
SELECT concept_title, COUNT(*) AS fails
FROM user_activity
WHERE space_dir = ?
  AND activity_type = 'code_run'
  AND ts >= datetime('now', '-' || ? || ' days')
  AND json_extract(metadata, '$.success') = 0
  AND concept_title != ''
GROUP BY concept_title
HAVING fails >= ?

-- :name concepts_touched
SELECT DISTINCT concept_title
FROM user_activity
WHERE space_dir = ?
  AND concept_title != ''
  AND ts >= datetime('now', '-' || ? || ' days')
ORDER BY ts DESC

-- :name recent_media_notes
SELECT * FROM user_activity
WHERE space_dir = ?
  AND activity_type IN ('audio_note','video_note')
  AND ts >= datetime('now', '-' || ? || ' days')
ORDER BY ts DESC
LIMIT 50

-- :name activity_by_session
SELECT * FROM user_activity
WHERE session_id = ?
ORDER BY ts ASC
LIMIT 500

-- :name delete_old_activity
-- Preserves 'practice_test' and 'note' rows (they are primary learning records).
DELETE FROM user_activity
WHERE ts < datetime('now', '-' || ? || ' days')
  AND space_dir = ?
  AND activity_type NOT IN ('practice_test','note')

-- :name count_by_space
SELECT COUNT(*) AS cnt FROM user_activity WHERE space_dir = ?
