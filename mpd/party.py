import datetime
import json
import re
import requests
import qrcode
import qrcode.image.svg
import urllib.parse
import zipfile
import io
from . import oauth
from .db import get_db
from flask import (
    Blueprint, url_for, redirect, render_template,
    session, flash, request, make_response,
)


papp = Blueprint('party', __name__)


class JsonValidator:
    def __init__(self, content: str):
        self.error: str | None = 'Validator todo'
        self.data: dict | None = None  # unpacked content
        self.location: str | None = None  # from Nominatim
        self.validate(content)

    @property
    def pie(self):
        return json.dumps(self.data, ensure_ascii=False)

    @property
    def piece_count(self):
        return len(self.data['features'])

    def validate(self, content):
        if not content:
            self.error = 'Empty content'
            return
        try:
            data = json.loads(content)
        except:  # noqa
            self.error = 'Error decoding json'
            return
        if not data.get('features'):
            self.error = 'No features found'
            return

        features = []
        next_piece = 1
        pieces = set[str]()
        for f in data['features']:
            if 'geometry' not in f:
                continue
            if f['geometry']['type'] != 'Polygon':
                continue
            if len(f['geometry']['coordinates']) != 1:
                continue

            p = f.get('properties', {})
            piece_id = p.get('id') or p.get('ref') or p.get('piece')
            if piece_id is not None:
                piece_id = str(piece_id).strip()
                if piece_id in pieces:
                    self.error = f'Duplicate piece id "{piece_id}"'
                    return
            else:
                while str(next_piece) in pieces:
                    next_piece += 1
                piece_id = str(next_piece)
                next_piece += 1
            f['properties'] = {'id': piece_id}
            pieces.add(piece_id)
            features.append(f)

        if not features:
            self.error = 'No Polygon features found'
            return
        self.error = None
        self.data = {'type': 'FeatureCollection', 'features': features}
        self.location = self.detect_location()

    def detect_location(self) -> str | None:
        if not self.data:
            return None
        count = 0
        lat = 0.0
        lon = 0.0
        for f in self.data['features']:
            if f['geometry']['type'] != 'Polygon':
                continue
            plat = 0.0
            plon = 0.0
            for coord in f['geometry']['coordinates'][0]:
                plon += coord[0]
                plat += coord[1]
            pcount = len(f['geometry']['coordinates'][0])
            lon += plon / pcount
            lat += plat / pcount
            count += 1

        lat /= count
        lon /= count
        if abs(lat) < 0.1 and abs(lon) < 0.1:
            return None

        # Now do the Nominatim request
        resp = requests.get('https://nominatim.openstreetmap.org/reverse', {
            'format': 'jsonv2',
            'lat': lat,
            'lon': lon,
        })
        if resp.status_code != 200:
            return None
        data = resp.json().get('address')
        if not data:
            return None
        city = data.get('city') or data.get('town') or data.get('village') or data.get('hamlet') or data.get('place')
        state = data.get('state')
        country = data.get('country')
        # TODO: skip empty parts
        return f'{city}, {state}, {country}'


def plugin_id(party_id, piece_id):
    return f'mpd_{party_id}_{piece_id}'


@papp.route('/', endpoint='list')
def list_projects():
    user_id = session.get('user_id')
    db = get_db()
    cur = db.execute(
        'select * from parties '
        'order by scheduled desc, created desc '
        'limit 100')
    parties = cur.fetchall()
    today = datetime.date.today().isoformat()
    return render_template(
        'list.html', logged_in=user_id is not None, user_id=user_id,
        parties=parties, today=today)


@papp.route('/create', methods=['GET', 'POST'])
def create():
    if 'user_id' not in session:
        return redirect(url_for('party.list'))
    if request.method == 'POST':
        title = request.form['title'].strip()
        if not title:
            flash('Empty title lol')
        else:
            db = get_db()
            db.execute(
                'insert into parties (title, created, owner_id) '
                'values (?, ?, ?)',
                (title, round(datetime.datetime.now().timestamp()),
                 session['user_id'])
            )
            db.commit()
            return redirect(url_for('party.list'))
    return render_template('create.html')


@papp.route('/<int:party_id>', methods=['GET', 'POST'])
def party(party_id):
    db = get_db()
    party = db.execute(
        'select * from parties where party_id = ?', (party_id,)).fetchone()
    if not party:
        flash('Party not found')
        return redirect(url_for('party.list'))
    is_owner = 'user_id' in session and session['user_id'] == party['owner_id']

    if is_owner and request.method == 'POST':
        title = request.form['title'].strip()
        if not title:
            flash('Empty title lol')
        scheduled = request.form['scheduled']
        if not re.match(r'', scheduled):
            scheduled = None
        if 'json' in request.files and request.files['json'].filename:
            # Uploading a new JSON
            data = JsonValidator(request.files['json'].read())
            if data.error:
                flash(f'Error reading GeoJSON: {data.error}')
                return redirect(url_for('party.party', party_id=party_id))
            db.execute(
                'update parties set title = ?, scheduled = ?, pie = ?, '
                'location = ?, piece_count = ?  where party_id = ?',
                (title, scheduled, data.pie, data.location, data.piece_count,
                 party_id))
        else:
            db.execute(
                'update parties set title = ?, scheduled = ? '
                'where party_id = ?',
                (title, scheduled, party_id))
        db.commit()
        return redirect(url_for('party.party', party_id=party_id))

    pie = None if not party['pie'] else json.loads(party['pie'])
    return render_template(
        'party.html', is_owner=is_owner, party=party, pie=pie)


@papp.route('/delete/<int:party_id>')
def delete_party(party_id):
    db = get_db()
    party = db.execute(
        'select * from parties where party_id = ?', (party_id,)).fetchone()
    if not party:
        flash('Party not found')
        return redirect(url_for('party.party', party_id=party_id))
    is_owner = 'user_id' in session and session['user_id'] == party['owner_id']
    if not is_owner:
        flash('No permissions for that')
        return redirect(url_for('party.party', party_id=party_id))
    db.execute('delete from parties where party_id = ?', (party_id,))
    db.commit()
    flash('Party deleted')
    return redirect(url_for('party.list'))


@papp.route('/edit/<int:party_id>', methods=['GET', 'POST'])
def edit_pie(party_id):
    db = get_db()
    party = db.execute(
        'select * from parties where party_id = ?', (party_id,)).fetchone()
    if not party:
        flash('Party not found')
        return redirect(url_for('party.list'))
    is_owner = 'user_id' in session and session['user_id'] == party['owner_id']
    if not is_owner:
        flash('No permissions for that')
        return redirect(url_for('party.party', party_id=party_id))

    if request.method == 'POST':
        data = JsonValidator(request.form['pie'])
        if data.error:
            flash(f'Error reading GeoJSON: {data.error}')
            return redirect(url_for('party.party', party_id=party_id))
        db.execute(
            'update parties set pie = ?, '
            'location = ?, piece_count = ?  where party_id = ?',
            (data.pie, data.location, data.piece_count, party_id))
        return redirect(url_for('party.party', party_id=party_id))

    pie = None if not party['pie'] else json.loads(party['pie'])
    return render_template('edit.html', party=party, pie=pie)


@papp.route('/<int:party_id>/<piece_id>')
def piece(party_id, piece_id):
    db = get_db()
    party = db.execute(
        'select * from parties where party_id = ?', (party_id,)).fetchone()
    if not party:
        flash('Party not found')
        return redirect(url_for('party.list'))
    if not party['pie']:
        flash('No pie in the party')
        return redirect(url_for('party.list'))
    data = json.loads(party['pie'])
    piece = None
    for f in data['features']:
        if f['properties']['id'] == piece_id:
            piece = f
    if not piece:
        flash(f'Could not find piece "{piece_id}"')
        return redirect(url_for('party.list'))

    everydoor_url = url_for(
        'party.piece_ed_plugin', party_id=party_id,
        piece_id=piece_id, _external=True)
    everydoor_url = (f'https://every-door.app/plugin/{plugin_id(party_id, piece_id)}?'
                     f'url={urllib.parse.quote(everydoor_url)}&update=true')

    qr = qrcode.make(
        everydoor_url, image_factory=qrcode.image.svg.SvgPathImage,
        border=1, box_size=20)

    return render_template(
        'piece.html', party=party, piece=piece, everydoor=everydoor_url,
        qr=qr.to_string().decode())


@papp.route('/mpd_<int:party_id>_<piece_id>.edp')
def piece_ed_plugin(party_id, piece_id):
    db = get_db()
    party = db.execute(
        'select * from parties where party_id = ?', (party_id,)).fetchone()
    if not party:
        flash('Party not found')
        return redirect(url_for('party.list'))
    if not party['pie']:
        flash('No pie in the party')
        return redirect(url_for('party.list'))
    data = json.loads(party['pie'])
    piece = None
    for f in data['features']:
        if f['properties']['id'] == piece_id:
            piece = f
    if not piece:
        flash(f'Could not find piece "{piece_id}"')
        return redirect(url_for('party.list'))

    # Now prepare the zip file
    pluginyaml = f'''---
id: mpd_{party_id}_{piece_id}
name: Piece {piece_id} of {party['title']}
version: 1
overlays:
  - url: piece.geojson
'''
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as z:
        z.writestr('plugin.yaml', pluginyaml)
        z.writestr('piece.geojson', json.dumps(piece))

    resp = make_response(buffer.getvalue())
    resp.headers['Content-Type'] = 'application/zip'
    return resp


@papp.route('/login')
def login():
    url = url_for('party.authorize', _external=True)
    return oauth.openstreetmap.authorize_redirect(url)


@papp.route('/authorize')
def authorize():
    oauth.openstreetmap.authorize_access_token()
    resp = oauth.openstreetmap.get('user/details.json')
    resp.raise_for_status()
    profile = resp.json()
    user_id = profile['user']['id']
    # there is "display_name" if we need it
    session['user_id'] = user_id
    return redirect(url_for('party.list'))


@papp.route('/logout')
def logout():
    if 'user_id' in session:
        del session['user_id']
    return redirect(url_for('party.list'))
