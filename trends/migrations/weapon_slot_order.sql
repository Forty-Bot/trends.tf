BEGIN;
DROP VIEW weapon_pretty;
CREATE TYPE NEWSLOT AS ENUM (
	'primary',
	'secondary',
	'melee',
	'sentry',
	'building',
	'action',
	'taunt',
	'environment'
);
ALTER TABLE weapon ALTER slot TYPE NEWSLOT USING slot::TEXT::NEWSLOT;
DROP TYPE SLOT;
ALTER TYPE NEWSLOT RENAME TO SLOT;
CREATE VIEW weapon_pretty AS SELECT
	weaponid,
	coalesce(name, initcap(replace(weapon, '_', ' '))) AS weapon,
	slot
FROM weapon;
COMMIT;
