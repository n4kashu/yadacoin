import json
import hashlib
import os
import argparse

from uuid import uuid4
from flask import Flask, request, render_template, session
from ecdsa import NIST384p, SigningKey
from ecdsa.util import randrange_from_seed__trytryagain
from simplecrypt import encrypt, decrypt, DecryptionException


parser = argparse.ArgumentParser(description='Process some integers.')
parser.add_argument('--conf',
                help='set your config file')
args = parser.parse_args()

with open(args.conf) as f:
    config = json.loads(f.read())

public_key = config.get('public_key')
private_key = config.get('private_key')
# print sk.get_verifying_key().to_string().encode('hex')
# vk2 = VerifyingKey.from_string(pk.decode('hex'))
# print vk2.verify(signature, "message")

app = Flask(__name__)


class TransacationFactory(object):
    def __init__(self, receiver_sig, shared_secret, mode='send', value=1, fee=0.1):
        print '!!!!', mode
        self.receiver_sig = receiver_sig
        self.mode = mode
        self.rid = self.generate_rid()
        self.public_key = public_key
        self.private_key = private_key
        self.value = value
        self.fee = fee
        self.shared_secret = TU.hash(shared_secret)
        self.bulletin_secret = TU.generate_deterministic_signature()
        self.relationship = self.generate_relationship()
        self.encrypted_relationship = TU.encrypt(self.relationship.to_json())
        self.transaction_signature = self.generate_transaction_signature()
        self.transaction = self.generate_transaction()

    def generate_rid(self):
        if self.mode == 'send':
            string = TU.generate_deterministic_signature() + self.receiver_sig
        else:
            string = self.receiver_sig + TU.generate_deterministic_signature()
        return hashlib.sha256(string).digest().encode('hex')

    def generate_relationship(self):
        return Relationship(
            self.shared_secret,
            self.bulletin_secret
        )

    def generate_transaction(self):
        return Transaction(
            self.rid,
            self.transaction_signature,
            self.encrypted_relationship,
            self.public_key,
            self.value,
            self.fee
        )

    def generate_transaction_signature(self):
        return TU.generate_signature(
            self.rid + self.encrypted_relationship + str(self.value) + str(self.fee)
        )


class Transaction(object):
    def __init__(self, rid, transaction_signature, relationship, public_key, value=1, fee=0.1):
        self.rid = rid
        self.transaction_signature = transaction_signature
        self.relationship = relationship
        self.public_key = public_key
        self.value = value
        self.fee = fee

    def __dict__(self):
        return {
            'rid': self.rid,
            'id': self.transaction_signature,
            'relationship': self.relationship,
            'public_key': self.public_key,
            'value': self.value,
            'fee': self.fee
        }

    def to_json(self):
        return json.dumps(self.__dict__())


class Relationship(object):
    def __init__(self, shared_secret, bulletin_secret):
        self.shared_secret = shared_secret
        self.bulletin_secret = bulletin_secret

    def __dict__(self):
        return {
            'shared_secret': self.shared_secret,
            'bulletin_secret': self.bulletin_secret
        }

    def to_json(self):
        return json.dumps(self.__dict__())


class TU(object):  # Transaction Utilities
    @staticmethod
    def hash(message):
        return hashlib.sha256(message).digest().encode('hex')

    @staticmethod
    def generate_deterministic_signature():
        sk = SigningKey.from_string(private_key.decode('hex'))
        signature = sk.sign_deterministic(hashlib.sha256(private_key).digest().encode('hex'))
        return hashlib.sha256(signature.encode('hex')).digest().encode('hex')

    @staticmethod
    def generate_signature(message):
        sk = SigningKey.from_string(private_key.decode('hex'))
        signature = sk.sign(message)
        return signature.encode('hex')

    @staticmethod
    def encrypt(message):
        return encrypt(private_key, message).encode('hex')

    @staticmethod
    def save(items):
        if not isinstance(items, list):
            items = [items.__dict__(), ]
        else:
            items = [item.__dict__() for item in items]

        with open('miner_transactions.json', 'a+') as f:
            try:
                existing = json.loads(f.read())
            except:
                existing = []
            existing.extend(items)
            f.seek(0)
            f.truncate()
            f.write(json.dumps(existing, indent=4))
            f.truncate()


class BU(object):  # Blockchain Utilities
    @staticmethod
    def get_blocks():
        with open('blockchain.json', 'r') as f:
            blocks = json.loads(f.read()).get('blocks')
        return blocks

    @staticmethod
    def get_relationships():
        relationships = []
        for block in BU.get_blocks():
            for transaction in block.get('transactions'):
                try:
                    decrypted = decrypt(key, transaction['relationship'].decode('hex'))
                    relationship = json.loads(decrypted)
                    relationships.append(relationship)
                except DecryptionException:
                    continue
        return relationships

    @staticmethod
    def get_transaction_by_rid(selector):
        ds = TU.generate_deterministic_signature()
        selectors = [
            TU.hash(ds+selector),
            TU.hash(selector+ds)
        ]

        for block in BU.get_blocks():
            for transaction in block.get('transactions'):
                try:
                    if transaction.get('rid') in selectors:
                        return transaction
                except DecryptionException:
                    continue


@app.route('/')
def index():
    bulletin_secret = TU.generate_deterministic_signature()
    print bulletin_secret

    return render_template(
        'index.html',
        bulletin_secret=bulletin_secret,
        shared_secret=str(uuid4()),
        challenge=str(uuid4())
    )


@app.route('/create-relationship', methods=['GET', 'POST'])
def create_relationship():
    if request.method == 'GET':
        bulletin_secret = request.args.get('bulletin_secret')
        shared_secret = request.args.get('shared_secret')
        requester_rid = request.args.get('requester_rid')
        requested_rid = request.args.get('requested_rid')
    else:
        bulletin_secret = request.form.get('bulletin_secret')
        shared_secret = request.form.get('shared_secret')
        requester_rid = request.form.get('requester_rid')
        requested_rid = request.form.get('requested_rid')

    existing = BU.get_transaction_by_rid(bulletin_secret)

    transaction = TransacationFactory(
        bulletin_secret,
        shared_secret,
        'send' if not existing else 'receive'
    )

    TU.save(transaction.transaction)

    my_bulletin_secret = TU.generate_deterministic_signature()
    return render_template(
        'create-relationship.html',
        ref=request.args.get('ref'),
        shared_secret=shared_secret,
        bulletin_secret=my_bulletin_secret)


@app.route('/process-challenge')
def process_challenge():
    transaction = BU.get_transaction_by_rid(request.args.get('rel_gen'))
    answer = encrypt(
        transaction['relationship']['shared_secret'],
        request.args.get('challenge')
    )
    return render_template(
        'send-friend-request.html',
        ref=request.args.get('ref'),
        answer=answer
    )

@app.route('/login', methods=['POST'])
def login():
    hashsig = TU.generate_deterministic_signature()
    rid = hashlib.sha256(request.form['input_signature']+hashsig).digest().encode('hex')
    print 'login signature: ', hashsig
    print 'login input_signature: ', request.form['input_signature']
    with open('blockchain.json', 'r') as f:
        blocks = json.loads(f.read()).get('blocks')
    for block in blocks:
        for relationship in block.get('transactions'):
            try:
                decrypted = decrypt(key, relationship['body'].decode('hex'))
            except DecryptionException:
                continue

            transaction = json.loads(decrypted)
            if rid == transaction['rid']:
                return json.dumps({'authenticated': True})
    return json.dumps({'authenticated': False})


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
    print request.content_type
    print request.get_json()
    return json.dumps(request.get_json())

app.debug = True
app.secret_key = '23ljk2l3k4j'
app.run(port=config.get('port'))
