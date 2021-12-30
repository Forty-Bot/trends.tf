BEGIN;
ALTER TABLE chat ADD FOREIGN KEY (steamid64) REFERENCES player (steamid64);
ALTER TABLE chat DROP CONSTRAINT chat_logid_steamid64_fkey;
COMMIT;
