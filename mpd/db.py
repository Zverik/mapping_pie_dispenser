import sqlite3
import click
from flask import current_app, g


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    sql = '''
drop table if exists parties;
create table parties (
    party_id integer primary key autoincrement,
    title text not null,
    owner_id integer not null,
    created integer not null,
    scheduled text,
    pie text,
    location text,
    piece_count integer
);
'''
    db = get_db()
    db.executescript(sql)


@click.command('initdb')
def init_db_command():
    init_db()
    click.echo('OK')


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
