CREATE EXTENSION IF NOT EXISTS bloom;

DO $$ BEGIN
	CREATE OPERATOR CLASS enum_ops DEFAULT FOR TYPE anyenum USING bloom AS
		OPERATOR 1 =(anyenum, anyenum),
		FUNCTION 1 hashenum(anyenum);
EXCEPTION WHEN duplicate_object THEN
	NULL;
END $$;
