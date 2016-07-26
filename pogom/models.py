#!/usr/bin/python
# -*- coding: utf-8 -*-

import logging
import os
import smtplib
import subprocess

from peewee import Model, SqliteDatabase, InsertQuery, IntegerField,\
                   CharField, FloatField, BooleanField, DateTimeField
from datetime import datetime
from datetime import timedelta
from base64 import b64encode

from .utils import get_pokemon_name, get_args
from .transform import transform_from_wgs_to_gcj
from .customLog import printPokemon

args = get_args()
db = SqliteDatabase(args.db)
log = logging.getLogger(__name__)


class BaseModel(Model):
    class Meta:
        database = db

    @classmethod
    def get_all(cls):
        results = [m for m in cls.select().dicts()]
        if args.china:
            for result in results:
                result['latitude'],  result['longitude'] = \
                    transform_from_wgs_to_gcj(result['latitude'],  result['longitude'])
        return results


class Pokemon(BaseModel):
    # We are base64 encoding the ids delivered by the api
    # because they are too big for sqlite to handle
    encounter_id = CharField(primary_key=True)
    spawnpoint_id = CharField()
    pokemon_id = IntegerField()
    latitude = FloatField()
    longitude = FloatField()
    disappear_time = DateTimeField()

    @classmethod
    def get_active(cls):
        query = (Pokemon
                 .select()
                 .where(Pokemon.disappear_time > datetime.utcnow())
                 .dicts())

        pokemons = []
        for p in query:
            p['pokemon_name'] = get_pokemon_name(p['pokemon_id'])
            if args.china:
                p['latitude'], p['longitude'] = \
                    transform_from_wgs_to_gcj(p['latitude'], p['longitude'])
            pokemons.append(p)

        return pokemons


class Pokestop(BaseModel):
    pokestop_id = CharField(primary_key=True)
    enabled = BooleanField()
    latitude = FloatField()
    longitude = FloatField()
    last_modified = DateTimeField()
    lure_expiration = DateTimeField(null=True)
    active_pokemon_id = IntegerField(null=True)


class Gym(BaseModel):
    UNCONTESTED = 0
    TEAM_MYSTIC = 1
    TEAM_VALOR = 2
    TEAM_INSTINCT = 3

    gym_id = CharField(primary_key=True)
    team_id = IntegerField()
    guard_pokemon_id = IntegerField()
    gym_points = IntegerField()
    enabled = BooleanField()
    latitude = FloatField()
    longitude = FloatField()
    last_modified = DateTimeField()

class ScannedLocation(BaseModel):
    scanned_id = CharField(primary_key=True)
    latitude = FloatField()
    longitude = FloatField()
    last_modified = DateTimeField()

    @classmethod
    def get_recent(cls):
        query = (ScannedLocation
                 .select()
                 .where(ScannedLocation.last_modified >= (datetime.utcnow() - timedelta(minutes=15)))
                 .dicts())

        scans = []
        for s in query:
            scans.append(s)

        return scans

def send_email(pokemon_name, id, latitude,longitude, expiry_time):

    msg = u'{} Id: {} @ {},{} till {}'.format(pokemon_name,id,latitude,longitude, expiry_time)

    # Send the message via our own SMTP server, but don't include the
    # envelope header.
    #s = smtplib.SMTP('localhost')
    #s.starttls()
    #s.login("maverick2202@yahoo.com","Ar@17623")
    #s.sendmail("maverick2202@yahoo.com", "maverick2202@hotmail.com", msg)
    #s.quit()


    command = u"mail -s \"{}\" maverick2202@hotmail.com < /dev/null".format(msg)

    log.info(u'Running: {}'.format(command))
    os.system(command)
    #process = subprocess.Popen(command,
    #                           stdout=subprocess.PIPE,
    #                           stderr=subprocess.STDOUT)
    #out, _ = process.communicate()
    #if not out:
    #    out = '<empty>'

    #log.info('STDOUT:\n' + out)
    #if process.returncode != 0:
    #    log.error('Command returned %d' % process.returncode)
    #else:
    #    log.info('Command returned %d' % process.returncode)


def parse_map(map_dict, iteration_num, step, step_location):
    rare_pokemon_ids = [1,2,3,4,5,6,7,29,30,31,32,33,34,35,36,43,44,45,58,60,61,62,66,67,68,69,70,71,72,73,79,80, 88, 92,93,94,89,129]
    high_cp_pokemon_ids =  [59,103,130,131,134,136,142,143,144,145,146,149,150,151]
    pokemons = {}
    pokestops = {}
    gyms = {}
    scanned = {}

    cells = map_dict['responses']['GET_MAP_OBJECTS']['map_cells']
    for cell in cells:
        for p in cell.get('wild_pokemons', []):
            d_t = datetime.utcfromtimestamp(
                (p['last_modified_timestamp_ms'] +
                 p['time_till_hidden_ms']) / 1000.0)
            if (p['pokemon_data']['pokemon_id'] in rare_pokemon_ids) or \
                (p['pokemon_data']['pokemon_id'] in high_cp_pokemon_ids): 

                pokemon_name = get_pokemon_name(p['pokemon_data']['pokemon_id'])

                log.info(u"Pokemon: {} Id# {} ".format(pokemon_name, p['pokemon_data']['pokemon_id']))

                #if (p['pokemon_data']['pokemon_id'] in high_cp_pokemon_ids): 
                if p['pokemon_data']['pokemon_id'] in high_cp_pokemon_ids:
                    send_email(pokemon_name, p['pokemon_data']['pokemon_id'],p['latitude'],p['longitude'], d_t)

                printPokemon(p['pokemon_data']['pokemon_id'],p['latitude'],p['longitude'],d_t)
                pokemons[p['encounter_id']] = {
                    'encounter_id': b64encode(str(p['encounter_id'])),
                    'spawnpoint_id': p['spawnpoint_id'],
                    'pokemon_id': p['pokemon_data']['pokemon_id'],
                    'latitude': p['latitude'],
                    'longitude': p['longitude'],
                    'disappear_time': d_t
                }

        if iteration_num > 0 or step > 50:
            for f in cell.get('forts', []):
                if f.get('type') == 1:  # Pokestops
                        if 'lure_info' in f:
                            lure_expiration = datetime.utcfromtimestamp(
                                f['lure_info']['lure_expires_timestamp_ms'] / 1000.0)
                            active_pokemon_id = f['lure_info']['active_pokemon_id']
                        else:
                            lure_expiration, active_pokemon_id = None, None

                        pokestops[f['id']] = {
                            'pokestop_id': f['id'],
                            'enabled': f['enabled'],
                            'latitude': f['latitude'],
                            'longitude': f['longitude'],
                            'last_modified': datetime.utcfromtimestamp(
                                f['last_modified_timestamp_ms'] / 1000.0),
                            'lure_expiration': lure_expiration,
                            'active_pokemon_id': active_pokemon_id
                    }

                else:  # Currently, there are only stops and gyms
                    gyms[f['id']] = {
                        'gym_id': f['id'],
                        'team_id': f.get('owned_by_team', 0),
                        'guard_pokemon_id': f.get('guard_pokemon_id', 0),
                        'gym_points': f.get('gym_points', 0),
                        'enabled': f['enabled'],
                        'latitude': f['latitude'],
                        'longitude': f['longitude'],
                        'last_modified': datetime.utcfromtimestamp(
                            f['last_modified_timestamp_ms'] / 1000.0),
                    }

    if pokemons:
        log.info("Upserting {} pokemon".format(len(pokemons)))
        bulk_upsert(Pokemon, pokemons)

    #if pokestops:
    #    log.info("Upserting {} pokestops".format(len(pokestops)))
    #    bulk_upsert(Pokestop, pokestops)

    #if gyms:
    #    log.info("Upserting {} gyms".format(len(gyms)))
    #    bulk_upsert(Gym, gyms)

    scanned[0] = {
        'scanned_id': str(step_location[0])+','+str(step_location[1]),
        'latitude': step_location[0],
        'longitude': step_location[1],
        'last_modified': datetime.utcnow(),
    }

    bulk_upsert(ScannedLocation, scanned)

def bulk_upsert(cls, data):
    num_rows = len(data.values())
    i = 0
    step = 120

    while i < num_rows:
        log.debug("Inserting items {} to {}".format(i, min(i+step, num_rows)))
        InsertQuery(cls, rows=data.values()[i:min(i+step, num_rows)]).upsert().execute()
        i+=step



def create_tables():
    db.connect()
    db.create_tables([Pokemon, Pokestop, Gym, ScannedLocation], safe=True)
    db.close()
