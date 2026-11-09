"""Osmosis (rede Cosmos) para a compra do Dormant (0.32.274, pedido do dono em 09/11/2026: "add a DEX da rede Osmosis/Cosmos e a carteira").

Só biblioteca padrão, reaproveitando o secp256k1 de app/evm.py (RFC 6979, s baixo) e a lista BIP39 de app/cardano.py:
- frase de recuperação (Keplr, Leap, Cosmostation) → semente BIP39 → BIP32 m/44'/118'/0'/0/0 → endereço osmo1 (bech32 de RIPEMD-160(SHA-256(chave)));
  também aceita a chave privada em hex que a Keplr exporta;
- a transação é montada AQUI (protobuf da Cosmos SDK, SIGN_MODE_DIRECT): uma mensagem só, MsgSplitRouteSwapExactAmountIn do poolmanager,
  com remetente = a própria carteira e mínimo a receber. Ninguém de fora monta nada; o roteador oficial (SQS) só sugere as pools.
Campos conferidos no tx.proto e swap_route.proto da Osmosis (github osmosis-labs/osmosis, main, 09/11/2026).
"""
from __future__ import annotations

import hashlib
import hmac
import struct
import unicodedata

from . import evm
from .cardano import bech32_decode, bech32_encode, entropy

CHAIN_ID = "osmosis-1"
NATIVE = "uosmo"
MSG_SWAP = "/osmosis.poolmanager.v1beta1.MsgSplitRouteSwapExactAmountIn"
PUBKEY_URL = "/cosmos.crypto.secp256k1.PubKey"


# ------------------------------------------------------------------ RIPEMD-160 (o hashlib do servidor, com OpenSSL 3, não traz)
def ripemd160(msg: bytes) -> bytes:
    r1 = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 7, 4, 13, 1, 10, 6, 15, 3, 12, 0, 9, 5, 2, 14, 11, 8,
          3, 10, 14, 4, 9, 15, 8, 1, 2, 7, 0, 6, 13, 11, 5, 12, 1, 9, 11, 10, 0, 8, 12, 4, 13, 3, 7, 15, 14, 5, 6, 2,
          4, 0, 5, 9, 7, 12, 2, 10, 14, 1, 3, 8, 11, 6, 15, 13]
    r2 = [5, 14, 7, 0, 9, 2, 11, 4, 13, 6, 15, 8, 1, 10, 3, 12, 6, 11, 3, 7, 0, 13, 5, 10, 14, 15, 8, 12, 4, 9, 1, 2,
          15, 5, 1, 3, 7, 14, 6, 9, 11, 8, 12, 2, 10, 0, 4, 13, 8, 6, 4, 1, 3, 11, 15, 0, 5, 12, 2, 13, 9, 7, 10, 14,
          12, 15, 10, 4, 1, 5, 8, 7, 6, 2, 13, 14, 0, 3, 9, 11]
    s1 = [11, 14, 15, 12, 5, 8, 7, 9, 11, 13, 14, 15, 6, 7, 9, 8, 7, 6, 8, 13, 11, 9, 7, 15, 7, 12, 15, 9, 11, 7, 13, 12,
          11, 13, 6, 7, 14, 9, 13, 15, 14, 8, 13, 6, 5, 12, 7, 5, 11, 12, 14, 15, 14, 15, 9, 8, 9, 14, 5, 6, 8, 6, 5, 12,
          9, 15, 5, 11, 6, 8, 13, 12, 5, 12, 13, 14, 11, 8, 5, 6]
    s2 = [8, 9, 9, 11, 13, 15, 15, 5, 7, 7, 8, 11, 14, 14, 12, 6, 9, 13, 15, 7, 12, 8, 9, 11, 7, 7, 12, 7, 6, 15, 13, 11,
          9, 7, 15, 11, 8, 6, 6, 14, 12, 13, 5, 14, 13, 13, 7, 5, 15, 5, 8, 11, 14, 14, 6, 14, 6, 9, 12, 9, 12, 5, 15, 8,
          8, 5, 12, 9, 12, 5, 14, 6, 8, 13, 6, 5, 15, 13, 11, 11]
    k1 = [0x00000000, 0x5A827999, 0x6ED9EBA1, 0x8F1BBCDC, 0xA953FD4E]
    k2 = [0x50A28BE6, 0x5C4DD124, 0x6D703EF3, 0x7A6D76E9, 0x00000000]
    M = 0xFFFFFFFF

    def rol(x, n):
        return ((x << n) | (x >> (32 - n))) & M

    def f(j, x, y, z):
        return [x ^ y ^ z, (x & y) | (~x & z), (x | ~y) ^ z, (x & z) | (y & ~z), x ^ (y | ~z)][j // 16] & M

    h = [0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0]
    m = msg + b"\x80" + b"\x00" * ((55 - len(msg)) % 64) + struct.pack("<Q", 8 * len(msg))
    for blk in range(0, len(m), 64):
        x = struct.unpack("<16I", m[blk:blk + 64])
        a1, b1, c1, d1, e1 = h
        a2, b2, c2, d2, e2 = h
        for j in range(80):
            t = (rol((a1 + f(j, b1, c1, d1) + x[r1[j]] + k1[j // 16]) & M, s1[j]) + e1) & M
            a1, e1, d1, c1, b1 = e1, d1, rol(c1, 10), b1, t
            t = (rol((a2 + f(79 - j, b2, c2, d2) + x[r2[j]] + k2[j // 16]) & M, s2[j]) + e2) & M
            a2, e2, d2, c2, b2 = e2, d2, rol(c2, 10), b2, t
        t = (h[1] + c1 + d2) & M
        h[1], h[2], h[3], h[4], h[0] = (h[2] + d1 + e2) & M, (h[3] + e1 + a2) & M, (h[4] + a1 + b2) & M, (h[0] + b1 + c2) & M, t
    return struct.pack("<5I", *h)


# ------------------------------------------------------------------ chaves
def seed(phrase: str, passphrase: str = "") -> bytes:
    entropy(phrase)                                    # confere palavras e soma de verificação (mesma lista oficial da Cardano)
    p = unicodedata.normalize("NFKD", " ".join(phrase.lower().split())).encode()
    return hashlib.pbkdf2_hmac("sha512", p, ("mnemonic" + unicodedata.normalize("NFKD", passphrase)).encode(), 2048)


def compressed(key: int) -> bytes:
    x, y = evm._mul(key)
    return bytes([2 + (y & 1)]) + x.to_bytes(32, "big")


def bip32(seed_b: bytes, path: list[int]) -> int:
    i = hmac.new(b"Bitcoin seed", seed_b, hashlib.sha512).digest()
    k, c = int.from_bytes(i[:32], "big"), i[32:]
    for n in path:
        data = (b"\x00" + k.to_bytes(32, "big") if n >= 0x80000000 else compressed(k)) + n.to_bytes(4, "big")
        i = hmac.new(c, data, hashlib.sha512).digest()
        il = int.from_bytes(i[:32], "big")
        if il >= evm.N:
            raise ValueError("derivação inválida")
        k, c = (il + k) % evm.N, i[32:]
        if k == 0:
            raise ValueError("derivação inválida")
    return k


H = 0x80000000
PATH = [44 + H, 118 + H, H, 0, 0]


def address_of_pub(pub: bytes, hrp: str = "osmo") -> str:
    return bech32_encode(hrp, ripemd160(hashlib.sha256(pub).digest()))


def parse_secret(text: str) -> int:
    t = (text or "").strip()
    if len(t.split()) >= 12:
        return bip32(seed(t), PATH)
    return evm.parse_key(t)                             # chave privada em hex (Keplr → Exportar chave privada)


class Wallet:
    def __init__(self, secret: str):
        self.key = parse_secret(secret)
        self.pub = compressed(self.key)
        self.address = address_of_pub(self.pub)


def address_of(secret: str) -> str:
    return Wallet(secret).address


def valid_address(adr: str) -> bool:
    try:
        hrp, d = bech32_decode(adr)
        return hrp == "osmo" and len(d) in (20, 32)
    except ValueError:
        return False


# ------------------------------------------------------------------ protobuf (só o que a transação usa)
def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _f(num: int, v) -> bytes:
    if isinstance(v, int):
        return _varint(num << 3) + _varint(v) if v else b""
    b = v.encode() if isinstance(v, str) else bytes(v)
    return _varint(num << 3 | 2) + _varint(len(b)) + b if b else b""


def _any(type_url: str, value: bytes) -> bytes:
    return _f(1, type_url) + _f(2, value)


def swap_msg(sender: str, routes: list[tuple[list[tuple[int, str]], int]], denom_in: str, min_out: int) -> bytes:
    """MsgSplitRouteSwapExactAmountIn: sender=1, routes=2 {pools=1 {pool_id=1, token_out_denom=2}, token_in_amount=2}, token_in_denom=3,
    token_out_min_amount=4. Quantias como texto (cosmossdk.io/math.Int)."""
    rs = b""
    for pools, amt in routes:
        ps = b"".join(_f(1, _f(1, int(pid)) + _f(2, den)) for pid, den in pools)
        rs += _f(2, ps + _f(2, str(int(amt))))
    return _f(1, sender) + rs + _f(3, denom_in) + _f(4, str(int(min_out)))


def body(msgs: list[bytes], memo: str = "") -> bytes:
    return b"".join(_f(1, _any(MSG_SWAP, m)) for m in msgs) + _f(2, memo)


def auth_info(pub: bytes, sequence: int, fee_amount: int, gas: int, fee_denom: str = NATIVE) -> bytes:
    signer = _f(1, _any(PUBKEY_URL, _f(1, pub))) + _f(2, _f(1, _f(1, 1))) + _varint(3 << 3) + _varint(sequence)   # modo DIRECT; sequência mesmo se 0
    fee = _f(1, _f(1, fee_denom) + _f(2, str(int(fee_amount)))) + _f(2, int(gas))
    return _f(1, signer) + _f(2, fee)


def sign_doc(body_b: bytes, auth_b: bytes, account_number: int, chain_id: str = CHAIN_ID) -> bytes:
    return _f(1, body_b) + _f(2, auth_b) + _f(3, chain_id) + _varint(4 << 3) + _varint(account_number)


def sign(key: int, doc: bytes) -> bytes:
    _, r, s = evm.sign_hash(key, hashlib.sha256(doc).digest())
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def tx_raw(body_b: bytes, auth_b: bytes, sig: bytes) -> bytes:
    return _f(1, body_b) + _f(2, auth_b) + _f(3, sig)


def tx_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest().upper()
