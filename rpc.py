import json
import hashlib
import os
import argparse
import qrcode
import base64

from io import BytesIO
from uuid import uuid4
from ecdsa import NIST384p, SigningKey
from ecdsa.util import randrange_from_seed__trytryagain
from Crypto.Cipher import AES
from pbkdf2 import PBKDF2
from flask import Flask, request, render_template, session, redirect
from bitcoin.wallet import CBitcoinSecret, P2PKHBitcoinAddress
from blockchainutils import BU
from transactionutils import TU
from transaction import *
from graph import Graph


parser = argparse.ArgumentParser(description='Process some integers.')
parser.add_argument('--conf',
                help='set your config file')
args = parser.parse_args()

with open(args.conf) as f:
    config = json.loads(f.read())

public_key = config.get('public_key')
my_address = str(P2PKHBitcoinAddress.from_pubkey(public_key.decode('hex')))
private_key = config.get('private_key')
TU.private_key = private_key
BU.private_key = private_key
# print sk.get_verifying_key().to_string().encode('hex')
# vk2 = VerifyingKey.from_string(pk.decode('hex'))
# print vk2.verify(signature, "message")

app = Flask(__name__)

def make_qr(data):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)

    out = BytesIO()
    qr_img = qr.make_image()
    qr_img = qr_img.convert("RGBA")
    qr_img.save(out, 'PNG')
    out.seek(0)
    return u"data:image/png;base64," + base64.b64encode(out.getvalue()).decode('ascii')


def get_logged_in_user():
    user = None
    tests = []
    for block in BU.get_blocks():
        for transaction in block['transactions']:
            if 'challenge_code' in transaction and session['challenge_code'] == transaction['challenge_code']:
                tests = BU.get_transactions_by_rid(transaction['rid'], rid=True)
                for test in tests:
                    if 'relationship' in test and 'shared_secret' in test['relationship']:
                        cipher = Crypt(hashlib.sha256(test['relationship']['shared_secret']).digest().encode('hex'))
                        answer = cipher.decrypt(transaction['answer'])
                        if answer == transaction['challenge_code']:
                            user = {
                                'balance': BU.get_wallet_balance(transaction['to']),
                                'authenticated': True,
                                'rid': transaction['rid'],
                                'bulletin_secret': test['relationship']['bulletin_secret']
                            }
    return user if user else {'authenticated': False}


@app.route('/')
def index():  # demo site
    bulletin_secret = TU.get_bulletin_secret()
    shared_secret = str(uuid4())
    existing = BU.get_transactions()

    session.setdefault('challenge_code', str(uuid4()))
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    data = {
        'challenge_code': session['challenge_code'],
        'bulletin_secret': TU.get_bulletin_secret(),
        'shared_secret': shared_secret,
        'callbackurl': config.get('callbackurl'),
        'to': my_address
    }
    qr.add_data(json.dumps(data))
    qr.make(fit=True)

    login_out = BytesIO()
    qr_img = qr.make_image()
    qr_img = qr_img.convert("RGBA")
    qr_img.save(login_out, 'PNG')
    login_out.seek(0)
    authed_user = get_logged_in_user()

    if authed_user['authenticated']:
        rid = authed_user['rid']
    else:
        rid = ''

    return render_template(
        'index.html',
        user=authed_user,
        bulletin_secret=bulletin_secret,
        shared_secret=shared_secret,
        existing=existing,
        data=json.dumps(data, indent=4),
        challenge_code=session['challenge_code'],
        users=set([x['rid'] for x in BU.get_transactions() if x['rid'] != rid]),
        login_qrcode=u"data:image/png;base64," + base64.b64encode(login_out.getvalue()).decode('ascii'),
    )

@app.route('/create-relationship', methods=['GET', 'POST'])
def create_relationship():  # demo site
    if request.method == 'GET':
        bulletin_secret = request.args.get('bulletin_secret', '')
        shared_secret = request.args.get('shared_secret', '')
        requester_rid = request.args.get('requester_rid', '')
        requested_rid = request.args.get('requested_rid', '')
        to = request.args.get('to', '')
    else:
        bulletin_secret = request.json.get('bulletin_secret', '')
        shared_secret = request.json.get('shared_secret', '')
        requester_rid = request.json.get('requester_rid', '')
        requested_rid = request.json.get('requested_rid', '')
        to = request.json.get('to', '')

    inputs = BU.get_wallet_unspent_transactions(my_address)

    transaction = TransactionFactory(
        bulletin_secret=bulletin_secret,
        shared_secret=shared_secret,
        value=1,
        fee=0.1,
        requester_rid=requester_rid,
        requested_rid=requested_rid,
        public_key=public_key,
        private_key=private_key,
        to=to,
        inputs=[Input(
            transaction_signature=input_txn.get('id', ''),
            rid=input_txn.get('rid', ''),
            relationship=input_txn.get('relationship', ''),
            public_key=input_txn.get('public_key', ''),
            value=input_txn.get('value', ''),
            fee=input_txn.get('fee', ''),
            requester_rid=input_txn.get('requester_rid', ''),
            requested_rid=input_txn.get('requested_rid', ''),
            challenge_code=input_txn.get('challenge_code', ''),
            answer=input_txn.get('answer', ''),
            txn_hash=input_txn.get('hash', ''),
            post_text=input_txn.get('post_text', ''),
            to=input_txn.get('to', ''),
            inputs=input_txn.get('inputs', ''),
            coinbase=True
        ) for input_txn in inputs]
    )

    TU.save(transaction.transaction)

    my_bulletin_secret = TU.get_bulletin_secret()

    return json.dumps({"success": True})

@app.route('/login-status')
def login_status():
    user = get_logged_in_user()
    return json.dumps(user)

@app.route('/show-user')
def show_user():
    authed_user = get_logged_in_user()
    user = BU.get_transaction_by_rid(request.args['rid'], rid=True)
    dict_data = {
        'bulletin_secret': user['relationship']['bulletin_secret'],
        'requested_rid': user['rid'],
        'requester_rid': authed_user['rid'],
        'to': user['to']
    }
    data = json.dumps(dict_data)
    qr_code = make_qr(data)
    return render_template(
        'show-user.html',
        qrcode=qr_code,
        data=json.dumps(dict_data, indent=4),
        bulletin_secret=user['relationship']['bulletin_secret'],
        to=user['to']
    )



@app.route('/show-friend-request')
def show_friend_request():
    authed_user = get_logged_in_user()

    transaction = BU.get_transaction_by_rid(request.args.get('rid'), rid=True, raw=True)

    requested_transaction = BU.get_transaction_by_rid(transaction['requester_rid'], rid=True)
    dict_data = {
        'bulletin_secret': requested_transaction['relationship']['bulletin_secret'],
        'requested_rid': transaction['requested_rid'],
        'requester_rid': transaction['requester_rid']
    }
    data = json.dumps(dict_data)
    qr_code = make_qr(data)
    return render_template(
        'accept-friend-request.html',
        qrcode=qr_code,
        data=json.dumps(dict_data, indent=4),
        rid=requested_transaction['rid'],
        bulletin_secret=requested_transaction['relationship']['bulletin_secret']
    )
peer_to_rid = {}
rid_to_peer = {}
@app.route('/add-peer')
def add_peer():
    #authed_user = get_logged_in_user()
    peer_to_rid[request.args['peer_id']] = request.args['rid']
    rid_to_peer[request.args['rid']] = request.args['peer_id']
    print peer_to_rid
    print rid_to_peer
    return 'ok'

@app.route('/get-peer')
def get_peer():
    #authed_user = get_logged_in_user()
    #TODO: verify this user is has a friend request from the rid
    # graph = Graph()
    if 'rid' in request.args:
        return json.dumps({'peerId': rid_to_peer[request.args['rid']]})

    if 'peer_id' in request.args:
        return json.dumps({'rid': peer_to_rid[request.args['peer_id']]})

    return '{}'

@app.route('/show-users')
def show_users():
    users = BU.get_transactions()
    rids = set([x['rid'] for x in users])
    return render_template('show-users.html', users=rids)


@app.route('/get-block/<index>')
def get_block(index=None):
    return json.dumps({'hi':index})


@app.route('/get-latest-block')
def get_latest_block():
    return json.dumps({'hi':'latest block'})


@app.route('/get-chain')
def get_chain():
    # some type of generator
    return json.dumps()


@app.route('/get-peers')
def get_peers():
    with open('peers.json') as f:
        peers = f.read()
    return json.dumps({'peers': peers})


@app.route('/post-block', methods=['POST'])
def post_block():
    return json.dumps(request.get_json())


@app.route('/transaction', methods=['GET', 'POST'])
def transaction():
    if request.method == 'POST':
        items = request.json
        if not isinstance(items, list):
            items = [items, ]
        else:
            items = [item for item in items]
        transactions = []
        for txn in items:
            transaction = Transaction(
                transaction_signature=txn.get('id'),
                rid=txn.get('rid', ''),
                relationship=txn.get('relationship', ''),
                public_key=txn.get('public_key'),
                value=txn.get('value'),
                fee=txn.get('fee'),
                requester_rid=txn.get('requester_rid', ''),
                requested_rid=txn.get('requested_rid', ''),
                challenge_code=txn.get('challenge_code', ''),
                answer=txn.get('answer', ''),
                txn_hash=txn.get('hash', ''),
                post_text=txn.get('post_text', ''),
                to=txn.get('to', ''),
                inputs=[Input(
                    transaction_signature=input_txn.get('id', ''),
                    rid=input_txn.get('rid', ''),
                    relationship=input_txn.get('relationship', ''),
                    public_key=input_txn.get('public_key', ''),
                    value=input_txn.get('value', ''),
                    fee=input_txn.get('fee', ''),
                    requester_rid=input_txn.get('requester_rid', ''),
                    requested_rid=input_txn.get('requested_rid', ''),
                    challenge_code=input_txn.get('challenge_code', ''),
                    answer=input_txn.get('answer', ''),
                    txn_hash=input_txn.get('hash', ''),
                    post_text=input_txn.get('post_text', ''),
                    to=input_txn.get('to', ''),
                    inputs=input_txn.get('inputs', ''),
                    coinbase=True
                ) for input_txn in txn.get('inputs', '')]
            )
            transactions.append(transaction)
        with open('miner_transactions.json', 'a+') as f:
            try:
                existing = json.loads(f.read())
            except:
                existing = []
            existing.extend([x.toDict() for x in transactions])
            f.seek(0)
            f.truncate()
            f.write(json.dumps(existing, indent=4))
            f.truncate()
        return json.dumps(request.get_json())
    else:
        rid = request.args.get('rid')
        transaction = BU.get_transactions_by_rid(rid, rid=True, raw=True)
        return json.dumps(transaction)


@app.route('/bulletins')
def bulletin():
    bulletin_secret = request.args.get('bulletin_secret')
    bulletins = BU.get_bulletins(bulletin_secret)
    return json.dumps(bulletins)


@app.route('/get-graph-mobile')
def get_graph_mobile():
    bulletin_secret = request.args.get('bulletin_secret')
    graph = Graph(bulletin_secret)

    return graph.toJson()


@app.route('/get-graph')
def get_graph():
    graph = Graph(TU.get_bulletin_secret(), for_me=True)

    return graph.toJson()

@app.route('/wallet')
def get_wallet():
    address = request.args.get('address')
    wallet = {
        'balance': BU.get_wallet_balance(address),
        'unspent_transactions': BU.get_wallet_unspent_transactions(address)
    }
    return json.dumps(wallet, indent=4)

app.debug = True
app.secret_key = '23ljk2l3k4j'
app.run(host=config.get('host'), port=config.get('port'))
