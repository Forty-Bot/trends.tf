#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2021 Sean Anderson <seanga2@gmail.com>

import argparse
import json
import os
import re
import sys
import time

import requests

SLOTS = frozenset((
    'action',
    'building',
    'environment',
    'melee',
    'primary',
    'secondary',
    'sentry',
    'taunt',
))

def items_to_json(items):
    # encapsulate in braces
    items = "{\n%s\n}" % items
    # replace open braces
    items = re.sub(r'"([^"]*)"(\s*){', r'"\1": {', items)
    # escape backslashes (from windows-style paths)
    items = re.sub(r'\\', r'\\\\', items)
    # remove tabs
    items = re.sub(r'\t', r' ', items)
    # replace values
    items = re.sub(r'"([^"]*)"\s*"([^"]*)"', r'"\1": "\2",', items)
    # remove trailing commas
    items = re.sub(r',(\s*[}\]])', r'\1', items)
    # add commas
    items = re.sub(r'([}\]])(\s*)("[^"]*":\s*)?([{\[])', r'\1,\2\3\4', items)
    # object as value
    items = re.sub(r'}(\s*"[^"]*":)',  r'},\1', items)
    return json.loads(items)

def parse_weapons(items):
    items = items_to_json(items)
    weapons = {}
    slots = {}

    def set_base(name, slot, weapon):
        base = re.search(r'(tf_)?(weapon_)?(.*)', weapon).group(3)
        for k in (base, f"weapon_{base}", f"tf_weapon_{base}"):
            weapons[k] = name
            if slot:
                slots[k] = slot

    def resolve(item):
        if prefabs := item.get('prefab'):
            for prefab_name in reversed(prefabs.split(' ')):
                item = resolve(items['items_game']['prefabs'][prefab_name]) | item

        return item

    for item in reversed(items['items_game']['items'].values()):
        item = resolve(item)
        name = item['name']
        slot = item.get('item_slot')

        if logname := item.get('item_logname'):
            weapons[logname] = name
            if slot:
                slots[logname] = slot

        if item_class := item.get('item_class'):
            set_base(name, slot, item_class)

    for weapon, name in weapons.items():
        weapons[weapon] = re.search(r'(The )?(.*)', name).group(2)

    for proj, name, slot in (
        ('arrow', "Arrow", 'primary'),
        ('arrow_fire', "Flaming Arrow", 'primary'),
        ('balloffire', "Dragon's Fury Fireball", 'primary'),
        ('ball_ornament', "Wrap Assassin Ball", 'melee'),
        ('energy_ball', "Short Circuit Orb", 'secondary'),
        ('flare', "Flare", 'secondary'),
        ('flare_detonator', "Detonator Flare", 'secondary'),
        ('grapplinghook', "Grappling Hook", 'action'),
        ('healing_bolt', "Crusader's Crossbow Bolt", 'primary'),
        ('huntsman_flyingburn', "Flaming Arrow", 'primary'),
        ('mechanicalarmorb', "Short Circuit Orb", 'secondary'),
        ('pipe', "Grenade", 'primary'),
        ('pipe_remote', "Stickybomb", 'secondary'),
        ('promode', "Grenade", 'primary'),
        ('rocket', "Rocket", 'primary'),
        ('sentryrocket', "Sentry Rocket", 'sentry'),
        ('sticky', "Stickybomb", 'secondary'),
    ):
        weapons[f"deflect_{proj}"] = "{} Reflect".format(name)
        weapons[f"tf_projectile_{proj}"] = name
        slots[f"deflect_{proj}"] = 'primary'
        slots[f"tf_projectile_{proj}"] = slot

    for base, name, slot in (
        ('bat', "Bat", 'melee'),
        ('bottle', "Bottle", 'melee'),
        ('builder', "Sapper", 'building'),
        ('club', "Kukri", 'melee'),
        ('flamethrower', "Flamethrower", 'primary'),
        ('grappling_hook', "Grappling Hook", 'action'),
        ('grenadelauncher', "Grenade Launcher", 'primary'),
        ('knife', "Knife", 'melee'),
        ('medigun', "Medi Gun", 'secondary'),
        ('minigun', "Minigun", 'primary'),
        ('passtime_gun', "JACK", 'action'),
        ('pipebomblauncher', "Stickybomb Launcher", 'secondary'),
        ('pistol', "Pistol", 'secondary'),
        ('revolver', "Revolver", 'secondary'),
        ('rocketlauncher', "Rocket Launcher", 'primary'),
        ('scattergun', "Scattergun", 'primary'),
        ('shotgun', "Shotgun", 'secondary'), # Ambiguous :l
        ('shovel', "Shovel", 'melee'),
        ('smg', "SMG", 'secondary'),
        ('sniperrifle', "Sniper Rifle", 'primary'),
        ('spellbook', "Spell", 'action'),
        ('syringegun_medic', "Syringe Gun", 'primary'),
        ('wrench', "Wrench", 'melee'),
    ):
        set_base(name, slot, base)

    # The rest
    for logname, name, slot in (
        ('bleed_kill', "Bleeding", 'environment'),
        ('dragons_fury_bonus', "Dragon's Fury Bonus", 'primary'),
        ('eyeball_rocket', "MONOCULUS Eye Projectile", 'primary'),
        ('loose_cannon_explosion', "Loose Cannon", 'primary'),
        ('maxgun', "Lugermorph", 'secondary'),
        ('merasmus_player_bomb', "Bomb Head", 'action'),
        ('obj_minisentry', "Mini-Sentry", 'sentry'),
        ('obj_sentrygun', "Level 1 Sentry", 'sentry'),
        ('obj_sentrygun2', "Level 2 Sentry", 'sentry'),
        ('obj_sentrygun3', "Level 3 Sentry", 'sentry'),
        ('passtime_ball', "JACK", 'action'),
        ('pickaxe', "Pickaxe", 'melee'),
        ('pistol_scout', "Pistol", 'secondary'),
        ('prop_physics', "Environment", 'action'),
        ('point_hurt', "Necro Smasher", 'melee'),
        ('robot_arm_blender_kill', "Organ Grinder", 'taunt'),
        ('robot_arm_combo_kill', "Gunslinger Crit", 'taunt'),
        ('robot_arm_kill', "Gunslinger", 'taunt'),
        ('rocketpack_stomp', "Manntreads", 'secondary'),
        ('rtd_toxic', "RTD Poison", 'action'),
        ('rtd_instant_kills', "RTD Instant Kill", 'action'),
        ('samrevolver', "Big Kill", 'primary'),
        ('scorchshot', "Execution", 'taunt'),
        ('short_stop', "Shortstop", 'primary'),
        ('shotgun_hwg', "Shotgun", 'secondary'),
        ('shotgun_primary', "Shotgun", 'primary'),
        ('shotgun_pyro', "Shotgun", 'secondary'),
        ('shotgun_soldier', "Shotgun", 'secondary'),
        ('spellbook_athletic', "Minify", 'action'),
        ('spellbook_bats', "Swarm of Bats", 'action'),
        ('spellbook_blastjump', "Blast Jump", 'action'),
        ('spellbook_boss', "Summon MONOCULUS", 'action'),
        ('spellbook_fireball', "Fireball", 'action'),
        ('spellbook_lightning', "Ball O' Lightning", 'action'),
        ('spellbook_meteor', "Meteor Shower", 'action'),
        ('spellbook_mirv', "Pumpkin MIRV", 'action'),
        ('spellbook_skeleton', "Skeletons Horde", 'action'),
        ('spellbook_teleport', "Shadow Leap", 'action'),
        ('sticky_resistance', "Scottish Resistance", 'secondary'),
        ('taunt_demoman', "Decapitation", 'taunt'),
        ('taunt_engineer', "Organ Grinder", 'taunt'),
        ('taunt_guitar_kill', "Dischord", 'taunt'),
        ('taunt_heavy', "Showdown", 'taunt'),
        ('taunt_medic', "Spinal Tap", 'taunt'),
        ('taunt_pyro', "Hadouken", 'taunt'),
        ('taunt_scout', "Home Run", 'taunt'),
        ('taunt_sniper', "Skewer", 'taunt'),
        ('taunt_soldier', "Kamikaze", 'taunt'),
        ('taunt_soldier_lumbricus', "Kamikaze", 'taunt'),
        ('taunt_spy', "Fencing", 'taunt'),
        ('tf_pumpkin_bomb', "Pumpkin Bomb", 'environment'),
        ('tf_generic_bomb', "Explosion", 'environment'),
        ('the_rescue_ranger', "Rescue Ranger", 'primary'),
        ('trigger_hurt', "Environment", 'environment'),
        ('ullapool_caber_explosion', "Ullapool Caber", 'melee'),
        ('world', "Environment", 'environment'),
        ('world_spawn', "Environment Spawn", 'environment'),
        ('wrangler_kill', "Wrangled Sentry", 'sentry'),
    ):
        weapons[logname] = name
        slots[logname] = slot

    return weapons, slots

def import_weapons(c, items):
    weapons, slots = parse_weapons(items)

    cur = c.cursor()
    cur.execute("BEGIN;")
    for weapon, name in weapons.items():
        slot = slots.get(weapon)
        if slot not in SLOTS:
            slot = None

        cur.execute("""UPDATE weapon
                       SET name = %s, slot = %s
                       WHERE weapon = %s;""",
                    (name, slot, weapon))
    cur.execute("COMMIT;")

def create_weapons_parser(sub):
    weapons = sub.add_parser("weapons", help="Import weapons from items_game.txt")
    weapons_sub = weapons.add_subparsers()
    local = weapons_sub.add_parser("local", help="Import from a local file")
    local.set_defaults(importer=import_local)
    local.add_argument('--items', type=argparse.FileType('r'), metavar="ITEMS", default=sys.stdin,
                         help="path to items_game.txt")
    remote = weapons_sub.add_parser("remote", help="Import from a web server")
    remote.set_defaults(importer=import_remote)
    remote.add_argument('--expire', type=int, metavar="EXPIRE", default=7*24*60*60,
                         help="Always import if we haven't done so for EXPIRE seconds")
    remote.add_argument('--etag', type=str, metavar="ETAG", default="/var/tmp/items_game.etag",
                        help="The location to store the items_game.txt etag")
    remote.add_argument('--url', type=str, metavar="URL",
                        default="https://raw.githubusercontent.com/SteamDatabase/GameTracking-TF2/"
                                "master/tf/scripts/items/items_game.txt",
                        help="Location to fetch items_game.txt from")

def import_remote(args, c, mc):
    s = requests.Session()
    resp = s.head(args.url)
    resp.raise_for_status()
    try:
        with open(args.etag) as etag:
            if resp.headers['etag'] == etag.read() and \
                time.time() - os.path.getmtime(args.etag) < args.expire:
                    return
    except FileNotFoundError:
        pass

    with open(args.etag, 'w') as etag:
        resp = s.get(args.url)
        resp.raise_for_status()
        import_weapons(c, resp.text)
        etag.write(resp.headers['etag'])

def import_local(args, c, mc):
    import_weapons(c, args.items.read())
