CREATE TABLE IF NOT EXISTS ratings (
    user_id BIGINT PRIMARY KEY,
    wins INTEGER DEFAULT 0
    game_nickname TEXT NOT NULL
);
