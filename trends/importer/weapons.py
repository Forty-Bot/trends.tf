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

def import_weapons(c, items):
    items = items_to_json(items)
    weapons = {}

    def set_base(name, weapon):
        base = re.search(r'(tf_)?(weapon_)?(.*)', weapon).group(3)
        weapons[base] = name
        weapons["weapon_{}".format(base)] = name
        weapons["tf_weapon_{}".format(base)] = name

    def set_prefab(name, prefab_name, prefab):
        set_base(name, prefab_name)
        if logname := prefab.get('item_logname'):
            weapons[logname] = name
        if cls := prefab.get('item_class'):
            set_base(name, cls)

    for item in reversed(items['items_game']['items'].values()):
        name = item['name']
        if logname := item.get('item_logname'):
            weapons[logname] = name
        if prefabs := item.get('prefab'):
            for prefab_name in prefabs.split(' '):
                set_prefab(name, prefab_name, items['items_game']['prefabs'][prefab_name])
        if item_class := item.get('item_class'):
            set_base(name, item_class)

    for prefab_name, prefab in items['items_game']['prefabs'].items():
        if name := prefab.get('base_item_name'):
            set_prefab(name, prefab_name, prefab)

    for weapon, name in weapons.items():
        weapons[weapon] = re.search(r'(The )?(.*)', name).group(2)

    for proj, name in {
        'arrow': "Arrow",
        'arrow_fire': "Flaming Arrow",
        'balloffire': "Dragon's Fury Fireball",
        'ball_ornament': "Wrap Assassin Ball",
        'energy_ball': "Short Circuit Orb",
        'flare': "Flare",
        'flare_detonator': "Detonator Flare",
        'grapplinghook': "Grappling Hook",
        'healing_bolt': "Crusader's Crossbow Bolt",
        'huntsman_flyingburn': "Flaming Arrow",
        'mechanicalarmorb': "Short Circuit Orb",
        'pipe': "Grenade",
        'pipe_remote': "Stickybomb",
        'promode': "Grenade",
        'rocket': "Rocket",
        'sentryrocket': "Sentry Rocket",
        'sticky': "Stickybomb",
    }.items():
        weapons["deflect_{}".format(proj)] = "{} Reflect".format(name)
        weapons["tf_projectile_{}".format(proj)] = name

    for base, name in {
        'bat': "Bat",
        'bottle': "Bottle",
        'builder': "Sapper",
        'club': "Kukri",
        'flamethrower': "Flamethrower",
        'grappling_hook': "Grappling Hook",
        'grenadelauncher': "Grenade Launcher",
        'knife': "Knife",
        'medigun': "Medi Gun",
        'minigun': "Minigun",
        'passtime_gun': "JACK",
        'pipebomblauncher': "Stickybomb Launcher",
        'pistol': "Pistol",
        'revolver': "Revolver",
        'rocketlauncher': "Rocket Launcher",
        'scattergun': "Scattergun",
        'shotgun': "Shotgun",
        'shovel': "Shovel",
        'smg': "SMG",
        'sniperrifle': "Sniper Rifle",
        'spellbook': "Spell",
        'syringegun_medic': "Syringe Gun",
        'wrench': "Wrench",
    }.items():
        set_base(name, base)

    # The rest
    weapons |= {
        'bleed_kill': "Bleeding",
        'dragons_fury_bonus': "Dragon's Fury Bonus",
        'eyeball_rocket': "MONOCULUS Eye Projectile",
        'loose_cannon_explosion': "Loose Cannon",
        'maxgun': "Lugermorph",
        'merasmus_player_bomb': "Bomb Head",
        'obj_minisentry': "Mini-Sentry",
        'obj_sentrygun': "Level 1 Sentry",
        'obj_sentrygun2': "Level 2 Sentry",
        'obj_sentrygun3': "Level 3 Sentry",
        'passtime_ball': "JACK",
        'pickaxe': "Pickaxe",
        'pistol_scout': "Pistol",
        'prop_physics': "Environment",
        'point_hurt': "Necro Smasher",
        'robot_arm_blender_kill': "Organ Grinder",
        'robot_arm_combo_kill': "Gunslinger Crit",
        'robot_arm_kill': "Gunslinger",
        'rocketpack_stomp': "Manntreads",
        'rtd_toxic': "RTD Poison",
        'rtd_instant_kills': "RTD Instant Kill",
        'samrevolver': "Big Kill",
        'scorchshot': "Execution",
        'short_stop': "Shortstop",
        'shotgun_soldier': "Shotgun",
        'shotgun_pyro': "Shotgun",
        'shotgun_hwg': "Shotgun",
        'spellbook_athletic': "Minify",
        'spellbook_bats': "Swarm of Bats",
        'spellbook_blastjump': "Blast Jump",
        'spellbook_boss': "Summon MONOCULUS",
        'spellbook_fireball': "Fireball",
        'spellbook_lightning': "Ball O' Lightning",
        'spellbook_meteor': "Meteor Shower",
        'spellbook_mirv': "Pumpkin MIRV",
        'spellbook_skeleton': "Skeletons Horde",
        'spellbook_teleport': "Shadow Leap",
        'sticky_resistance': "Scottish Resistance",
        'taunt_demoman': "Decapitation",
        'taunt_engineer': "Organ Grinder",
        'taunt_guitar_kill': "Dischord",
        'taunt_heavy': "Showdown",
        'taunt_medic': "Spinal Tap",
        'taunt_pyro': "Hadouken",
        'taunt_scout': "Home Run",
        'taunt_sniper': "Skewer",
        'taunt_soldier': "Kamikaze",
        'taunt_soldier_lumbricus': "Kamikaze",
        'taunt_spy': "Fencing",
        'tf_pumpkin_bomb': "Pumpkin Bomb",
        'tf_generic_bomb': "Explosion",
        'the_rescue_ranger': "Rescue Ranger",
        'trigger_hurt': "Environment",
        'ullapool_caber_explosion': "Ullapool Caber",
        'world': "Environment",
        'world_spawn': "Environment Spawn",
        'wrangler_kill': "Wrangled Sentry",
    }

    cur = c.cursor()
    cur.execute("BEGIN;")
    for weapon, name in weapons.items():
        name = re.search(r'(The )?(.*)', name).group(2)
        cur.execute("UPDATE weapon SET name = %s WHERE weapon = %s;", (name, weapon))
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

def import_local(args, c):
    import_weapons(c, args.items.read())
