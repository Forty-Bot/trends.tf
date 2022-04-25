BEGIN;
ALTER TABLE log ADD uploader BIGINT;
ALTER TABLE log ADD uploader_nameid INT REFERENCES name (nameid);
ALTER TABLE log ADD CHECK (
	(uploader ISNULL AND uploader_nameid ISNULL)
		OR (uploader NOTNULL AND uploader_nameid NOTNULL)
);
COMMIT;
