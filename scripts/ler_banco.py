"""Consulta SÓ LEITURA no banco de produção com o usuário `leitor_ia` (0.32.2, pedido do dono em 2026-10-28).

Usa só a biblioteca padrão do Python (TLS + SCRAM-SHA-256 do protocolo do Postgres): nada para instalar.
A conexão fica FORA do repositório, em %USERPROFILE%\\.secrets\\pump.env, linha
    PUMP_DB_URL=postgresql://leitor_ia.vnvfluimpqvxbvdbmwqa:SENHA@aws-0-REGIAO.pooler.supabase.com:5432/postgres
(senha com caractere especial vai codificada, ex.: @ = %40). Opcional: PUMP_DB_CA=<caminho do certificado da Supabase>
para conferir o servidor; sem ele a conexão é cifrada mas sem conferir o certificado (igual ao sslmode=require).

O usuário do banco já é somente leitura (migração 20261028000009); o script também recusa o que não for consulta.

Uso:
    py -I scripts/ler_banco.py --teste
    py -I scripts/ler_banco.py "select count(*) from pump_trades"
    py -I scripts/ler_banco.py --arquivo consulta.sql --json > saida.json
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import ssl
import struct
import sys
from urllib.parse import unquote, urlparse

ENV = os.path.join(os.path.expanduser("~"), ".secrets", "pump.env")
SO_CONSULTA = re.compile(r"^\s*(select|with|explain|show|table)\b", re.I)


class DBErro(Exception):
    pass


def ler_env(path: str = ENV) -> dict:
    out = {}
    try:
        for ln in open(path, encoding="utf-8-sig"):
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        raise DBErro(f"não achei {path}: crie o arquivo com a linha PUMP_DB_URL=... (passo a passo no docs/LEITOR-BANCO.md)")
    if not out.get("PUMP_DB_URL"):
        raise DBErro(f"{path} não tem PUMP_DB_URL")
    return out


def scram_final(pw: str, first_bare: str, server_first: str) -> tuple[str, str]:
    """Mensagem final do cliente e assinatura esperada do servidor (RFC 5802/7677)."""
    f = dict(x.split("=", 1) for x in server_first.split(","))
    salted = hashlib.pbkdf2_hmac("sha256", pw.encode(), base64.b64decode(f["s"]), int(f["i"]))
    ck = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    final_wo = "c=biws,r=" + f["r"]
    auth = (first_bare + "," + server_first + "," + final_wo).encode()
    sig = hmac.new(hashlib.sha256(ck).digest(), auth, hashlib.sha256).digest()
    proof = bytes(a ^ b for a, b in zip(ck, sig))
    sk = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    return final_wo + ",p=" + base64.b64encode(proof).decode(), base64.b64encode(hmac.new(sk, auth, hashlib.sha256).digest()).decode()


class Conexao:
    def __init__(self, url: str, ca: str | None = None, timeout: float = 20):
        u = urlparse(url)
        if u.scheme not in ("postgres", "postgresql") or not u.hostname:
            raise DBErro("PUMP_DB_URL inválida (esperado postgresql://usuario:senha@host:porta/postgres)")
        self.user, self.pw = unquote(u.username or ""), unquote(u.password or "")
        self.db = (u.path or "/postgres").lstrip("/") or "postgres"
        raw = socket.create_connection((u.hostname, u.port or 5432), timeout=timeout)
        raw.sendall(struct.pack("!ii", 8, 80877103))                 # SSLRequest
        if raw.recv(1) != b"S":
            raw.close()
            raise DBErro("o servidor não aceitou conexão cifrada (TLS)")
        ctx = ssl.create_default_context(cafile=ca) if ca else ssl.create_default_context()
        if not ca:
            ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        self.s = ctx.wrap_socket(raw, server_hostname=u.hostname)
        self._buf = b""
        self._login()

    # ---- protocolo
    def _send(self, tipo: bytes, corpo: bytes) -> None:
        self.s.sendall(tipo + struct.pack("!i", len(corpo) + 4) + corpo)

    def _recv_n(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self.s.recv(65536)
            if not chunk:
                raise DBErro("conexão fechada pelo servidor")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _msg(self) -> tuple[bytes, bytes]:
        head = self._recv_n(5)
        return head[:1], self._recv_n(struct.unpack("!i", head[1:])[0] - 4)

    @staticmethod
    def _erro(corpo: bytes) -> str:
        campos = {p[:1]: p[1:].decode("utf-8", "replace") for p in corpo.split(b"\0") if p}
        return campos.get(b"M", "erro do banco") + (f" ({campos[b'C']})" if b"C" in campos else "")

    def _login(self) -> None:
        params = b"user\0" + self.user.encode() + b"\0database\0" + self.db.encode() + b"\0application_name\0leitor_ia_script\0\0"
        corpo = struct.pack("!i", 196608) + params
        self.s.sendall(struct.pack("!i", len(corpo) + 4) + corpo)
        nonce = base64.b64encode(secrets.token_bytes(18)).decode()
        first_bare = "n=,r=" + nonce
        server_sig = None
        while True:
            t, c = self._msg()
            if t == b"E":
                raise DBErro("login recusado: " + self._erro(c))
            if t == b"R":
                code = struct.unpack("!i", c[:4])[0]
                if code == 0:
                    continue
                if code == 10:                                         # SASL
                    if b"SCRAM-SHA-256" not in c:
                        raise DBErro("o servidor não oferece SCRAM-SHA-256")
                    msg = ("n,," + first_bare).encode()
                    self._send(b"p", b"SCRAM-SHA-256\0" + struct.pack("!i", len(msg)) + msg)
                elif code == 11:                                       # SASLContinue
                    sf = c[4:].decode()
                    f = dict(x.split("=", 1) for x in sf.split(","))
                    if not f["r"].startswith(nonce):
                        raise DBErro("resposta SCRAM inválida")
                    final, server_sig = scram_final(self.pw, first_bare, sf)
                    self._send(b"p", final.encode())
                elif code == 12:                                       # SASLFinal
                    if server_sig is None or c[4:].decode().split("v=", 1)[-1] != server_sig:
                        raise DBErro("o servidor não provou que é o banco certo (SCRAM)")
                elif code == 5:                                        # md5
                    inner = hashlib.md5((self.pw + self.user).encode()).hexdigest()
                    self._send(b"p", ("md5" + hashlib.md5(inner.encode() + c[4:8]).hexdigest()).encode() + b"\0")
                elif code == 3:
                    self._send(b"p", self.pw.encode() + b"\0")
                else:
                    raise DBErro(f"tipo de login não suportado ({code})")
            elif t == b"Z":
                return

    def consulta(self, sql: str, max_linhas: int = 5000) -> tuple[list[str], list[list]]:
        if not SO_CONSULTA.match(sql) or ";" in sql.strip().rstrip(";"):
            raise DBErro("só consultas (select/with/explain), uma por vez")
        self._send(b"Q", sql.encode() + b"\0")
        cols, tipos, linhas, erro = [], [], [], None
        while True:
            t, c = self._msg()
            if t == b"T":
                n, pos = struct.unpack("!h", c[:2])[0], 2
                cols, tipos = [], []
                for _ in range(n):
                    fim = c.index(b"\0", pos)
                    cols.append(c[pos:fim].decode())
                    tipos.append(struct.unpack("!i", c[fim + 7:fim + 11])[0])
                    pos = fim + 19
            elif t == b"D":
                n, pos, row = struct.unpack("!h", c[:2])[0], 2, []
                for i in range(n):
                    ln = struct.unpack("!i", c[pos:pos + 4])[0]
                    pos += 4
                    if ln < 0:
                        row.append(None)
                        continue
                    row.append(_conv(c[pos:pos + ln].decode("utf-8", "replace"), tipos[i] if i < len(tipos) else 25))
                    pos += ln
                if len(linhas) < max_linhas:
                    linhas.append(row)
            elif t == b"E":
                erro = self._erro(c)
            elif t == b"Z":
                if erro:
                    raise DBErro(erro)
                return cols, linhas

    def fechar(self) -> None:
        try:
            self._send(b"X", b"")
            self.s.close()
        except Exception:
            pass


def _conv(v: str, oid: int):
    if oid in (20, 21, 23):
        return int(v)
    if oid in (700, 701, 1700):
        return float(v)
    if oid == 16:
        return v == "t"
    if oid in (114, 3802):
        return json.loads(v)
    return v


def conectar(env_path: str = ENV) -> Conexao:
    env = ler_env(env_path)
    return Conexao(env["PUMP_DB_URL"], env.get("PUMP_DB_CA") or None)


def main() -> int:
    ap = argparse.ArgumentParser(description="consulta só leitura no banco do PUMP FUN COPY")
    ap.add_argument("sql", nargs="?")
    ap.add_argument("--arquivo")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--max", type=int, default=5000)
    ap.add_argument("--teste", action="store_true", help="confere a conexão e mostra o que dá para ler")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        db = conectar()
        if a.teste:
            cols, rows = db.consulta("select current_user, current_setting('default_transaction_read_only') as so_leitura, now()")
            print(dict(zip(cols, rows[0])))
            _, rows = db.consulta("select table_name from information_schema.role_table_grants where grantee = 'leitor_ia' "
                                  "group by table_name order by table_name")
            print("tabelas liberadas:", ", ".join(r[0] for r in rows))
            return 0
        sql = open(a.arquivo, encoding="utf-8").read() if a.arquivo else a.sql
        if not sql:
            ap.error("passe a consulta ou --arquivo")
        cols, rows = db.consulta(sql, a.max)
        if a.json:
            print(json.dumps([dict(zip(cols, r)) for r in rows], ensure_ascii=False, default=str))
        else:
            w = csv.writer(sys.stdout)
            w.writerow(cols)
            w.writerows([json.dumps(x, ensure_ascii=False) if isinstance(x, (dict, list)) else x for x in r] for r in rows)
        db.fechar()
        return 0
    except DBErro as e:
        print("ERRO:", e, file=sys.stderr)
        return 2
    except OSError as e:
        print("ERRO de conexão:", e, file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
