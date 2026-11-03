"""Assinatura de transação da BNB Chain (EVM) só com a biblioteca padrão (0.32.172).

Pedido do dono em 03/11/2026: carteira REAL na BNB. Para não instalar pacote novo (regra do projeto: nenhuma dependência
sem triagem e OK), keccak-256, secp256k1 (RFC 6979, s baixo da EIP-2), RLP e a transação legada da EIP-155 estão aqui.
Conferido com os vetores oficiais: keccak de "Transfer(address,address,uint256)", endereço da chave 1 e a transação
assinada de exemplo da EIP-155 (tests/test_evm.py).
"""
from __future__ import annotations

import hashlib
import hmac

# ------------------------------------------------------------------ keccak-256 (não é o SHA3 do hashlib: o padding muda)
_RC = [0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000, 0x000000000000808B,
       0x0000000080000001, 0x8000000080008081, 0x8000000000008009, 0x000000000000008A, 0x0000000000000088,
       0x0000000080008009, 0x000000008000000A, 0x000000008000808B, 0x800000000000008B, 0x8000000000008089,
       0x8000000000008003, 0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
       0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008]
_ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61], [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]]
_M = (1 << 64) - 1


def _rol(x: int, n: int) -> int:
    n %= 64
    return ((x << n) | (x >> (64 - n))) & _M if n else x


def _f(A):
    for rc in _RC:
        C = [A[x][0] ^ A[x][1] ^ A[x][2] ^ A[x][3] ^ A[x][4] for x in range(5)]
        D = [C[(x - 1) % 5] ^ _rol(C[(x + 1) % 5], 1) for x in range(5)]
        A = [[A[x][y] ^ D[x] for y in range(5)] for x in range(5)]
        B = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                B[y][(2 * x + 3 * y) % 5] = _rol(A[x][y], _ROT[x][y])
        A = [[B[x][y] ^ ((~B[(x + 1) % 5][y]) & B[(x + 2) % 5][y]) for y in range(5)] for x in range(5)]
        A[0][0] ^= rc
    return A


def keccak256(data: bytes) -> bytes:
    r = 136
    p = bytearray(data)
    p.append(1)
    while len(p) % r:
        p.append(0)
    p[-1] |= 0x80
    A = [[0] * 5 for _ in range(5)]
    for i in range(0, len(p), r):
        blk = p[i:i + r]
        for j in range(r // 8):
            A[j % 5][j // 5] ^= int.from_bytes(blk[8 * j:8 * j + 8], "little")
        A = _f(A)
    return b"".join(A[j % 5][j // 5].to_bytes(8, "little") for j in range(4))


def selector(sig: str) -> str:
    return "0x" + keccak256(sig.encode()).hex()[:8]


# ------------------------------------------------------------------ secp256k1
P = 2 ** 256 - 2 ** 32 - 977
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
G = (0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
     0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8)


def _add(a, b):
    if a is None:
        return b
    if b is None:
        return a
    if a[0] == b[0] and (a[1] + b[1]) % P == 0:
        return None
    if a == b:
        lam = 3 * a[0] * a[0] * pow(2 * a[1], -1, P) % P
    else:
        lam = (b[1] - a[1]) * pow(b[0] - a[0], -1, P) % P
    x = (lam * lam - a[0] - b[0]) % P
    return x, (lam * (a[0] - x) - a[1]) % P


def _mul(k: int, pt=G):
    out = None
    while k:
        if k & 1:
            out = _add(out, pt)
        pt = _add(pt, pt)
        k >>= 1
    return out


def parse_key(value: str) -> int:
    """Chave privada em hexadecimal (64 dígitos, com ou sem 0x). Levanta ValueError com texto para a tela."""
    v = (value or "").strip().lower()
    if v.startswith("0x"):
        v = v[2:]
    if len(v) != 64 or any(c not in "0123456789abcdef" for c in v):
        raise ValueError("chave privada inválida: use os 64 caracteres hexadecimais exportados da carteira (MetaMask, Trust…)")
    k = int(v, 16)
    if not 0 < k < N:
        raise ValueError("chave privada fora do intervalo válido")
    return k


def address_of(key: int) -> str:
    x, y = _mul(key)
    return "0x" + keccak256(x.to_bytes(32, "big") + y.to_bytes(32, "big"))[-20:].hex()


def _k6979(key: int, h: bytes) -> int:
    x = key.to_bytes(32, "big")
    hv = (int.from_bytes(h, "big") % N).to_bytes(32, "big")
    V, K = b"\x01" * 32, b"\x00" * 32
    K = hmac.new(K, V + b"\x00" + x + hv, hashlib.sha256).digest()
    V = hmac.new(K, V, hashlib.sha256).digest()
    K = hmac.new(K, V + b"\x01" + x + hv, hashlib.sha256).digest()
    V = hmac.new(K, V, hashlib.sha256).digest()
    while True:
        V = hmac.new(K, V, hashlib.sha256).digest()
        k = int.from_bytes(V, "big")
        if 0 < k < N:
            return k
        K = hmac.new(K, V + b"\x00", hashlib.sha256).digest()
        V = hmac.new(K, V, hashlib.sha256).digest()


def sign_hash(key: int, h: bytes) -> tuple[int, int, int]:
    """(recid, r, s) com s baixo (EIP-2)."""
    z = int.from_bytes(h, "big")
    k = _k6979(key, h)
    R = _mul(k)
    r = R[0] % N
    s = pow(k, -1, N) * (z + r * key) % N
    rec = R[1] & 1
    if s > N // 2:
        s, rec = N - s, rec ^ 1
    return rec, r, s


# ------------------------------------------------------------------ RLP e transação
def _rlp_item(b: bytes) -> bytes:
    if len(b) == 1 and b[0] < 0x80:
        return b
    return _rlp_len(len(b), 0x80) + b


def _rlp_len(n: int, off: int) -> bytes:
    if n < 56:
        return bytes([off + n])
    nb = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([off + 55 + len(nb)]) + nb


def _int(v: int) -> bytes:
    return v.to_bytes((v.bit_length() + 7) // 8, "big") if v else b""


def rlp(items: list) -> bytes:
    body = b"".join(_rlp_item(x) if isinstance(x, bytes) else rlp(x) for x in items)
    return _rlp_len(len(body), 0xC0) + body


def sign_tx(key: int, nonce: int, gas_price: int, gas: int, to: str, value: int, data: str, chain_id: int) -> tuple[str, str]:
    """Transação legada da EIP-155 assinada. Devolve (raw em hex com 0x, hash da transação)."""
    to_b = bytes.fromhex(to[2:] if to.startswith("0x") else to)
    data_b = bytes.fromhex((data or "0x")[2:])
    base = [_int(nonce), _int(gas_price), _int(gas), to_b, _int(value), data_b]
    rec, r, s = sign_hash(key, keccak256(rlp(base + [_int(chain_id), b"", b""])))
    raw = rlp(base + [_int(rec + chain_id * 2 + 35), _int(r), _int(s)])
    return "0x" + raw.hex(), "0x" + keccak256(raw).hex()


# ------------------------------------------------------------------ ABI
def w_int(v: int) -> str:
    return hex(int(v))[2:].rjust(64, "0")


def w_addr(a: str) -> str:
    return a[2:].lower().rjust(64, "0")


def call_data(sel: str, *args) -> str:
    """Só tipos estáticos (address em texto 0x…, uint256 em int) e um address[] no fim (lista)."""
    head, tail = [], []
    n = len(args)
    for a in args:
        if isinstance(a, list):
            head.append(w_int(32 * n + 32 * sum(len(t) // 64 for t in tail)))
            tail.append(w_int(len(a)) + "".join(w_addr(x) for x in a))
        elif isinstance(a, str):
            head.append(w_addr(a))
        else:
            head.append(w_int(a))
    return sel + "".join(head) + "".join(tail)


def words(h: str) -> list[int]:
    h = (h or "0x")[2:]
    return [int(h[64 * i:64 * (i + 1)], 16) for i in range(len(h) // 64)]
