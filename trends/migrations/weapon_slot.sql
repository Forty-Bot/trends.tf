BEGIN;
CREATE TYPE SLOT AS ENUM (
	'action',
	'building',
	'environment',
	'melee',
	'primary',
	'secondary',
	'sentry',
	'taunt'
);
ALTER TABLE weapon ADD slot SLOT;
CREATE OR REPLACE VIEW weapon_pretty AS SELECT
	weaponid,
	coalesce(name, initcap(replace(weapon, '_', ' '))) AS weapon,
	slot
FROM weapon;
COMMIT;
