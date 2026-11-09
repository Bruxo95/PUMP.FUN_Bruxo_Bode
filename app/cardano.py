"""Cardano para a compra do Dormant (0.32.273, pedido do dono em 09/11/2026: "adicione a carteira Cardano e a Minswap").

Só biblioteca padrão + cryptography (já no projeto), sem pacote novo:
- frase de recuperação BIP39 (lista oficial em bip39_english.txt, SHA-256 conferido) → chave mestra Icarus (CIP-3);
- derivação BIP32-Ed25519 (CIP-1852) m/1852'/1815'/0'/0/0 (pagamento) e m/1852'/1815'/0'/2/0 (stake): o primeiro endereço de Eternl, Lace e Yoroi;
- endereço base (CIP-19) em bech32 e assinatura Ed25519 com a chave estendida;
- leitura do CBOR da transação montada pela Minswap, para conferir antes de assinar.
Vetores oficiais nos testes: chave mestra do CIP-3, chave e endereço de stake do CIP-11, endereço base do CIP-19.
"""
from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

# ------------------------------------------------------------------ bech32 (sem o limite de 90 letras: endereço Cardano passa disso)
_CH = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _polymod(vals: list[int]) -> int:
    g = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    c = 1
    for v in vals:
        b = c >> 25
        c = ((c & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            c ^= g[i] if (b >> i) & 1 else 0
    return c


def _hrp_exp(h: str) -> list[int]:
    return [ord(x) >> 5 for x in h] + [0] + [ord(x) & 31 for x in h]


def _bits(data: bytes, frm: int, to: int, pad: bool) -> list[int]:
    acc = bits = 0
    out, mx = [], (1 << to) - 1
    for v in data:
        acc = (acc << frm) | v
        bits += frm
        while bits >= to:
            bits -= to
            out.append((acc >> bits) & mx)
    if pad and bits:
        out.append((acc << (to - bits)) & mx)
    elif not pad and (bits >= frm or ((acc << (to - bits)) & mx)):
        raise ValueError("bech32 com sobra")
    return out


def bech32_encode(hrp: str, data: bytes) -> str:
    d = _bits(data, 8, 5, True)
    pm = _polymod(_hrp_exp(hrp) + d + [0] * 6) ^ 1
    return hrp + "1" + "".join(_CH[x] for x in d + [(pm >> 5 * (5 - i)) & 31 for i in range(6)])


def bech32_decode(s: str) -> tuple[str, bytes]:
    s = s.strip()
    if s.lower() != s and s.upper() != s:
        raise ValueError("bech32 misturando maiúsculas")
    s = s.lower()
    p = s.rfind("1")
    if p < 1 or len(s) - p < 7:
        raise ValueError("bech32 inválido")
    hrp, d = s[:p], [_CH.find(x) for x in s[p + 1:]]
    if -1 in d or _polymod(_hrp_exp(hrp) + d) != 1:
        raise ValueError("bech32 com soma errada")
    return hrp, bytes(_bits(bytes(d[:-6]), 5, 8, False))


# ------------------------------------------------------------------ Ed25519 (aritmética da curva, para assinar com a chave estendida)
P = 2 ** 255 - 19
L = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, P - 2, P) % P
_I = pow(2, (P - 1) // 4, P)


def _xrec(y: int, sign: int) -> int:
    xx = (y * y - 1) * pow(_D * y * y + 1, P - 2, P)
    x = pow(xx, (P + 3) // 8, P)
    if (x * x - xx) % P:
        x = x * _I % P
    if x % 2 != sign:
        x = P - x
    return x


_BY = 4 * pow(5, P - 2, P) % P
_B = (_xrec(_BY, 0), _BY, 1, _xrec(_BY, 0) * _BY % P)


def _add(a, b):
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    A, Bv = (y1 - x1) * (y2 - x2) % P, (y1 + x1) * (y2 + x2) % P
    C, Dv = t1 * 2 * _D * t2 % P, z1 * 2 * z2 % P
    E, F, G, H = Bv - A, Dv - C, Dv + C, Bv + A
    return (E * F % P, G * H % P, F * G % P, E * H % P)


def _mul(s: int, pt=_B):
    q = (0, 1, 1, 0)
    while s:
        if s & 1:
            q = _add(q, pt)
        pt = _add(pt, pt)
        s >>= 1
    return q


def _enc(pt) -> bytes:
    x, y, z, _ = pt
    zi = pow(z, P - 2, P)
    x, y = x * zi % P, y * zi % P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def pub_of(kl: bytes) -> bytes:
    return _enc(_mul(int.from_bytes(kl, "little")))


def sign(kl: bytes, kr: bytes, msg: bytes) -> bytes:
    """Assinatura Ed25519 com a chave estendida (kL = escalar, kR = prefixo do nonce)."""
    a = int.from_bytes(kl, "little")
    pk = pub_of(kl)
    r = int.from_bytes(hashlib.sha512(kr + msg).digest(), "little") % L
    rb = _enc(_mul(r))
    k = int.from_bytes(hashlib.sha512(rb + pk + msg).digest(), "little") % L
    sig = rb + int.to_bytes((r + k * a) % L, 32, "little")
    try:                                                 # confere com uma implementação independente antes de usar
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(pk).verify(sig, msg)
    except ImportError:
        pass
    return sig


# ------------------------------------------------------------------ frase → chaves → endereço
_WORDS: list[str] = []


def words() -> list[str]:
    if not _WORDS:
        w = (Path(__file__).with_name("bip39_english.txt")).read_text("utf-8").split()
        if len(w) != 2048 or hashlib.sha256(("\n".join(w) + "\n").encode()).hexdigest() != \
                "2f5eed53a4727b4bf8880d8f3f199efc90e58503646d9ff8eff3a2ed3b24dbda":
            raise ValueError("lista de palavras BIP39 alterada")
        _WORDS.extend(w)
    return _WORDS


def entropy(phrase: str) -> bytes:
    ws = phrase.lower().split()
    if len(ws) not in (12, 15, 18, 21, 24):
        raise ValueError("a frase de recuperação tem 12, 15, 18, 21 ou 24 palavras")
    idx = {w: i for i, w in enumerate(words())}
    try:
        n = 0
        for w in ws:
            n = n << 11 | idx[w]
    except KeyError:
        raise ValueError("uma das palavras não está na lista oficial (confira a grafia)") from None
    tot = len(ws) * 11
    cs = tot // 33
    ent = (n >> cs).to_bytes((tot - cs) // 8, "big")
    if hashlib.sha256(ent).digest()[0] >> (8 - cs) != n & ((1 << cs) - 1):
        raise ValueError("a frase de recuperação não confere (palavra errada ou fora de ordem)")
    return ent


def master(ent: bytes, passphrase: bytes = b"") -> bytes:
    k = bytearray(hashlib.pbkdf2_hmac("sha512", passphrase, ent, 4096, 96))
    k[0] &= 0b11111000
    k[31] &= 0b00011111
    k[31] |= 0b01000000
    return bytes(k)


def derive(xprv: bytes, path: list[int]) -> bytes:
    """BIP32-Ed25519 (V2). xprv = kL(32) + kR(32) + código da corrente(32)."""
    kl, kr, cc = xprv[:32], xprv[32:64], xprv[64:]
    for i in path:
        ib = i.to_bytes(4, "little")
        if i >= 0x80000000:
            z = hmac.new(cc, b"\x00" + kl + kr + ib, "sha512").digest()
            c2 = hmac.new(cc, b"\x01" + kl + kr + ib, "sha512").digest()[32:]
        else:
            a = pub_of(kl)
            z = hmac.new(cc, b"\x02" + a + ib, "sha512").digest()
            c2 = hmac.new(cc, b"\x03" + a + ib, "sha512").digest()[32:]
        kl = ((int.from_bytes(z[:28], "little") * 8 + int.from_bytes(kl, "little")) % 2 ** 256).to_bytes(32, "little")
        kr = ((int.from_bytes(z[32:], "little") + int.from_bytes(kr, "little")) % 2 ** 256).to_bytes(32, "little")
        cc = c2
    return kl + kr + cc


H = 0x80000000
PATH_PAY = [1852 + H, 1815 + H, H, 0, 0]
PATH_STAKE = [1852 + H, 1815 + H, H, 2, 0]


def h224(b: bytes) -> bytes:
    return hashlib.blake2b(b, digest_size=28).digest()


def base_address(pay_pub: bytes, stake_pub: bytes) -> str:
    return bech32_encode("addr", b"\x01" + h224(pay_pub) + h224(stake_pub))


class Wallet:
    """Chaves da frase de recuperação. A frase não é guardada aqui: só as duas chaves que assinam, enquanto o objeto existir."""

    def __init__(self, phrase: str):
        root = master(entropy(phrase))
        pay = derive(root, PATH_PAY)
        self.kl, self.kr = pay[:32], pay[32:64]
        self.pub = pub_of(self.kl)
        self.stake_pub = pub_of(derive(root, PATH_STAKE)[:32])
        self.address = base_address(self.pub, self.stake_pub)
        self.pay_hash = h224(self.pub)
        self.addr_bytes = bech32_decode(self.address)[1]

    def witness_set(self, body_hash: bytes) -> str:
        """{0: [[chave pública, assinatura]]}: o que a Minswap pede no finalize-and-submit-tx."""
        sig = sign(self.kl, self.kr, body_hash)
        return (b"\xa1\x00\x81\x82\x58\x20" + self.pub + b"\x58\x40" + sig).hex()


def address_of(phrase: str) -> str:
    return Wallet(phrase).address


# ------------------------------------------------------------------ CBOR (só leitura, guardando onde cada pedaço começa e termina)
class Tag:
    def __init__(self, tag: int, value):
        self.tag, self.value = tag, value


def _cbor(b: bytes, i: int):
    ib = b[i]
    mt, ai = ib >> 5, ib & 31
    i += 1
    if ai < 24:
        n = ai
    elif ai in (24, 25, 26, 27):
        sz = 1 << (ai - 24)
        n = int.from_bytes(b[i:i + sz], "big")
        i += sz
    elif ai == 31:
        n = None
    else:
        raise ValueError("CBOR inválido")
    if mt == 0:
        return n, i
    if mt == 1:
        return -1 - n, i
    if mt in (2, 3):
        if n is None:
            parts = []
            while b[i] != 0xFF:
                v, i = _cbor(b, i)
                parts.append(v)
            return (b"" if mt == 2 else "").join(parts), i + 1
        v = b[i:i + n]
        return (v if mt == 2 else v.decode("utf-8", "replace")), i + n
    if mt == 4:
        out = []
        while (n is None and b[i] != 0xFF) or (n is not None and len(out) < n):
            v, i = _cbor(b, i)
            out.append(v)
        return out, (i + 1 if n is None else i)
    if mt == 5:
        out, k = {}, 0
        while (n is None and b[i] != 0xFF) or (n is not None and k < n):
            kk, i = _cbor(b, i)
            v, i = _cbor(b, i)
            out[kk if not isinstance(kk, (list, dict, Tag)) else repr(kk)] = v
            k += 1
        return out, (i + 1 if n is None else i)
    if mt == 6:
        v, i = _cbor(b, i)
        return Tag(n, v), i
    if mt == 7:
        return {20: False, 21: True, 22: None}.get(ai, n), i
    raise ValueError("CBOR inválido")


def loads(b: bytes):
    v, i = _cbor(b, 0)
    return v


def tx_parts(cbor_hex: str) -> tuple[dict, bytes]:
    """(corpo decodificado, bytes exatos do corpo). O hash assinado é o blake2b-256 desses bytes, não de uma recodificação."""
    b = bytes.fromhex(cbor_hex)
    if b[0] >> 5 != 4:
        raise ValueError("a transação não é uma lista CBOR")
    i = 1 if (b[0] & 31) < 24 else 2
    start = i
    body, end = _cbor(b, start)
    if not isinstance(body, dict):
        raise ValueError("corpo da transação inválido")
    return body, b[start:end]


def body_hash(body_bytes: bytes) -> bytes:
    return hashlib.blake2b(body_bytes, digest_size=32).digest()


def _items(x):
    return list(x.value) if isinstance(x, Tag) else list(x or [])


def _out(o) -> tuple[bytes, int, dict]:
    """Saída → (endereço em bytes, lovelace, {policy+nome: quantidade}). Aceita o formato antigo (lista) e o novo (mapa)."""
    if isinstance(o, list):
        adr, val = o[0], o[1]
    else:
        adr, val = o.get(0), o.get(1)
    if isinstance(val, int):
        return adr, val, {}
    lov, ma = int(val[0]), {}
    for pol, assets in (val[1] or {}).items():
        pol_b = pol if isinstance(pol, bytes) else bytes.fromhex(str(pol))
        for name, q in (assets or {}).items():
            nb = name if isinstance(name, bytes) else bytes.fromhex(str(name))
            ma[(pol_b + nb).hex()] = ma.get((pol_b + nb).hex(), 0) + int(q)
    return adr, lov, ma


def same_wallet(adr: bytes, w: Wallet) -> bool:
    """Endereço da própria carteira: mesma chave de pagamento (base 0x01 ou só pagamento 0x61), rede principal."""
    return isinstance(adr, bytes) and len(adr) >= 29 and adr[0] in (0x01, 0x61) and adr[1:29] == w.pay_hash


class TxRejected(ValueError):
    pass


def check_tx(cbor_hex: str, w: Wallet, *, max_out_lovelace: int, token_out: str | None = None, max_token_out: int = 0,
             max_fee: int = 3_000_000) -> tuple[bytes, dict]:
    """Confere a transação da Minswap ANTES de assinar. Devolve (hash do corpo, resumo).

    O que sai da carteira para fora tem limite: em ADA, no máximo max_out_lovelace (valor + taxas da DEX/agregador + depósito que volta);
    em token, só o token da venda e no máximo max_token_out. Nada de certificado (delegação, registro), saque de recompensa, criação de
    moeda, voto ou doação ao tesouro. Taxa da rede até max_fee. Garantia (collateral) só se voltar quase inteira."""
    body, raw = tx_parts(cbor_hex)
    for k, why in ((4, "certificado (delegação ou registro)"), (5, "saque de recompensas"), (9, "criação ou queima de moeda"),
                   (19, "voto"), (20, "proposta de governança"), (21, "doação ao tesouro"), (22, "doação ao tesouro"), (6, "atualização de protocolo")):
        if body.get(k):
            raise TxRejected(f"a transação traz {why}: não é uma troca")
    fee = int(body.get(2) or 0)
    if fee > max_fee:
        raise TxRejected(f"taxa da rede alta demais ({fee / 1e6:.2f} ADA)")
    if body.get(1) is None or not _items(body.get(0)):
        raise TxRejected("transação sem entradas ou sem saídas")
    out_ada, out_tok, outs = 0, 0, []
    for o in body.get(1) or []:
        adr, lov, ma = _out(o)
        mine = same_wallet(adr, w)
        outs.append({"minha": mine, "ada": lov / 1e6, "tokens": len(ma)})
        if mine:
            continue
        out_ada += lov
        for unit, q in ma.items():
            if token_out and unit == token_out.lower():
                out_tok += q
            else:
                raise TxRejected("uma saída leva para fora um token que não é o da venda")
    if out_ada > max_out_lovelace:
        raise TxRejected(f"saem {out_ada / 1e6:.2f} ADA para fora, acima do previsto ({max_out_lovelace / 1e6:.2f} ADA)")
    if out_tok > max_token_out:
        raise TxRejected("sai mais token do que o vendido")
    if token_out and max_token_out and out_tok <= 0:
        raise TxRejected("o token da venda não sai em nenhuma saída")
    if body.get(13):                                     # garantia só é gasta se um script falhar; tem que voltar para a carteira
        ret = body.get(16)
        if ret is None or not same_wallet(_out(ret)[0], w):
            raise TxRejected("a transação usa garantia (collateral) sem devolver para a carteira")
        tc = body.get(17)
        if tc is not None and int(tc) > max_fee * 2:
            raise TxRejected("garantia alta demais")
    return body_hash(raw), {"taxa_rede": fee / 1e6, "sai_ada": out_ada / 1e6, "sai_token": out_tok, "saidas": outs}


def received(cbor_hex: str, w: Wallet, unit: str) -> tuple[int, int]:
    """(lovelace, quantidade do token) que a transação devolve para a própria carteira."""
    body, _ = tx_parts(cbor_hex)
    lov = tok = 0
    for o in body.get(1) or []:
        adr, l_, ma = _out(o)
        if same_wallet(adr, w):
            lov += l_
            tok += ma.get(unit.lower(), 0)
    return lov, tok
