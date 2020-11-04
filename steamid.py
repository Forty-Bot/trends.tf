# SPDX-License-Identifier: MIT
# Copyright (c) 2017 Nate the great

import re

class SteamID:
    Universe = {
        "INVALID": 0,
        "PUBLIC": 1,
        "BETA": 2,
        "INTERVAL": 3,
        "DEV": 4
    }

    Type = {
        "INVALID": 0,
        "INDIVIDUAL": 1,
        "MULTISEAT": 2,
        "GAMESERVER": 3,
        "ANON_GAMESERVER": 4,
        "PENDING": 5,
        "CONTENT_SERVER": 6,
        "CLAN": 7,
        "CHAT": 8,
        "P2P_SUPER_SEEDER": 9,
        "ANON_USER": 10
    }

    Instance = {
        "ALL": 0,
        "DESKTOP": 1,
        "CONSOLE": 2,
        "WEB": 4
    }

    TypeChars = {}
    TypeChars[Type["INVALID"]] = 'I'
    TypeChars[Type["INDIVIDUAL"]] = 'U'
    TypeChars[Type["MULTISEAT"]] = 'M'
    TypeChars[Type["GAMESERVER"]] = 'G'
    TypeChars[Type["ANON_GAMESERVER"]] = 'A'
    TypeChars[Type["PENDING"]] = 'P'
    TypeChars[Type["CONTENT_SERVER"]] = 'C'
    TypeChars[Type["CLAN"]] = 'g'
    TypeChars[Type["CHAT"]] = 'T'
    TypeChars[Type["ANON_USER"]] = 'a'

    AccountIDMask = 0xFFFFFFFF
    AccountInstanceMask = 0x000FFFFF

    ChatInstanceFlags = {
        "Clan": (AccountInstanceMask + 1) >> 1,
        "Lobby": (AccountInstanceMask + 1) >> 2,
        "MMSLobby": (AccountInstanceMask + 1) >> 3
    }

    def __init__(self, input):
        self.universe = SteamID.Universe["INVALID"]
        self.type = SteamID.Universe["INVALID"]
        self.instance = SteamID.Instance["ALL"]

        if not input:
            return

        reg = re.compile("^STEAM_([0-5]):([0-1]):([0-9]+)$")
        reg3 = re.compile("^\[([a-zA-Z]):([0-5]):([0-9]+)(:[0-9]+)?\]")
        mat = reg.match(input)
        mat3 = reg3.match(input)
        if mat:
            self.universe = int(mat[1]) or SteamID.Universe["PUBLIC"]
            self.type = SteamID.Type["INDIVIDUAL"]
            self.instance = SteamID.Instance["DESKTOP"]
            self.accountid = int(mat[3]) * 2 + int(mat[2])
        elif mat3:
            self.universe = int(mat3[2])
            self.accountid = int(mat3[3])

            typeChar = mat3[1]

            if mat3[4]:
                self.instance = int(mat3[4][1:])
            elif typeChar == 'U':
                self.instance = SteamID.Instance["DESKTOP"]

            if typeChar == 'c':
                self.instance = self.instance or SteamID.ChatInstanceFlags["Clan"]
                self.type = SteamID.Type["CHAT"]
            elif typeChar == 'L':
                self.instance = self.instance or SteamID.ChatInstanceFlags["Lobby"]
                self.type = SteamID.Type["CHAT"]
            else:
                self.type = getTypeFromChar(typeChar)

        elif not input:
            raise ValueError("Unknown ID: {}".format(input))
        else:
            input = int(input)
            # Credit to the python steam modual, for the bit operations
            self.accountid = input & 0xFFffFFff
            self.instance = (input >> 32) & 0xFFffF
            self.type = (input >> 52) & 0xF
            self.universe = (input >> 56) & 0xFF

    @staticmethod
    def fromIndividualAccountID(accountid):
        sid = SteamID(None)
        sid.universe = SteamID.Universe["PUBLIC"]
        sid.type = SteamID.Type["INDIVIDUAL"]
        sid.instance = SteamID.Instance["DESKTOP"]
        sid.accountid = 0 if not accountid else int(accountid)

    def steam2(self, newerFormat):
        if self.type != SteamID.Type["INDIVIDUAL"]:
            raise ValueError("Can't get Steam2 rendered ID for non-individual ID")
        universe = self.universe
        if not newerFormat and universe == 1:
            universe = 0
        return "STEAM_" + str(universe) + ':' + str(self.accountid & 1) + ':' + str(self.accountid // 2)

    def getSteam2RenderedID(self, newerFormat):
        return self.steam2(newerFormat)

    def steam3(self):
        typeChar = SteamID.TypeChars[self.type] if self.type in SteamID.TypeChars else 'i'

        if self.instance & SteamID.ChatInstanceFlags["Clan"]:
            typeChar = 'c'
        elif self.instance & SteamID.ChatInstanceFlags["Lobby"]:
            typeChar = 'L'

        renderInstance = (self.type == SteamID.Type["ANON_GAMESERVER"]
                          or self.type == SteamID.Type["MULTISEAT"] or
                          (self.type == SteamID.Type["INDIVIDUAL"] and
                           self.instance != SteamID.Instance["DESKTOP"]))

        return '[' + typeChar + ':' + str(self.universe) + ':' + \
               str(self.accountid) + (str(self.instance) if renderInstance else '') + ']'

    def getSteam3RenderedID(self):
        return self.steam3()

    def __str__(self):
        return str((self.universe << 56) | (self.type << 52) | (self.instance << 32) | self.accountid)

    def __bool__(self):
        return self.isValid()

    def getSteamID64(self):
        return self.__str__()

    def isValid(self):
        if self.type <= SteamID.Type["INVALID"] or \
                        self.type > SteamID.Type["ANON_USER"]:
            return False
        if self.universe <= SteamID.Universe["INVALID"] or \
                        self.universe > SteamID.Universe["DEV"]:
            return False
        if self.type == SteamID.Type["INDIVIDUAL"] and \
                (self.accountid == 0 or self.instance > SteamID.Instance["WEB"]):
            return False
        if self.type == SteamID.Type["CLAN"] and \
                (self.accountid == 0 or self.instance != SteamID.Instance["ALL"]):
            return False
        if self.type == SteamID.Type["GAMESERVER"] and self.accountid == 0:
            return False
        return True


def getTypeFromChar(typeChar):
    for typ in SteamID.TypeChars:
        if SteamID.TypeChars[typ] == typeChar:
            return int(typ)
    return SteamID.Type["INVALID"]
