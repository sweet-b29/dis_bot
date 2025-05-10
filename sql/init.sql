CREATE TABLE IF NOT EXISTS ratings (
    user_id BIGINT PRIMARY KEY,
    matches INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    game_nickname TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS player_profiles (
    user_id BIGINT PRIMARY KEY,
    username TEXT NOT NULL,
    rank TEXT NOT NULL,
    last_name_change TIMESTAMP
);
