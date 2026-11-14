"""0.32.351 (pedido do dono, 14/11/2026): músicas lofi de verdade na SALA LIVE do BOT LIVE, em 4 playlists que trocam sozinhas
pelo horário do computador que transmite:

  madrugada (0–6 h)  · para dormir      · LATE NIGHT
  manha     (6–12 h) · café da manhã    · MORNING CAFÉ
  trabalho  (12–18 h)· concentração     · FOCUS
  noite     (18–24 h)· relax            · NIGHT RELAX

As faixas (livres de direitos autorais, ex.: Pixabay Music) são enviadas pelo admin em /botlive e ficam num bucket privado do
Supabase Storage ("botlive-music"); a lista fica no próprio bucket (index.json). A SALA LIVE (inclusive pelo link do OBS, sem login)
lê a lista e toca cada faixa pela rota /botlive/musica/<id>. Sem faixa no período, toca as de outro período; sem nenhuma, a música
gerada no navegador (como antes).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from collections import OrderedDict

PERIODOS = {
    "madrugada": {"de": 0, "ate": 6, "nome": "Madrugada · para dormir", "en": "LATE NIGHT"},
    "manha": {"de": 6, "ate": 12, "nome": "Manhã · café da manhã", "en": "MORNING CAFÉ"},
    "trabalho": {"de": 12, "ate": 18, "nome": "Trabalho · concentração", "en": "FOCUS"},
    "noite": {"de": 18, "ate": 24, "nome": "Noite · relax", "en": "NIGHT RELAX"},
}
BUCKET = "botlive-music"
MAX_BYTES = 25 * 1024 * 1024
MAX_FAIXAS = 80
CACHE_MAX = 6                     # faixas guardadas na memória (o OBS toca uma por vez)
LINK_TTL = 6 * 3600               # o link de cada faixa vale 6 h (a SALA LIVE relê a lista a cada 10 min)
IMPORT_HOSTS = ("cdn.pixabay.com",)   # de onde o servidor aceita baixar música pelo "importar" (sem SSRF)


def audio_type(data: bytes) -> str | None:
    """MP3 (com ou sem ID3) ou OGG; qualquer outra coisa é recusada."""
    if data[:3] == b"ID3" or (len(data) > 1 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0):
        return "audio/mpeg"
    if data[:4] == b"OggS":
        return "audio/ogg"
    return None


def clean(s, n: int = 80) -> str:
    return " ".join(str(s or "").split())[:n]


class MemStorage:
    """Para os testes (e sem Supabase): guarda os arquivos na memória."""

    def __init__(self):
        self.files: dict[str, tuple[bytes, str]] = {}

    async def put(self, path: str, data: bytes, ctype: str) -> None:
        self.files[path] = (data, ctype)

    async def get(self, path: str) -> bytes | None:
        v = self.files.get(path)
        return v[0] if v else None

    async def remove(self, path: str) -> None:
        self.files.pop(path, None)


class SupaStorage:
    """Supabase Storage com a service key (só o servidor fala com ele; o bucket é privado)."""

    def __init__(self, http, url: str, service_key: str):
        self.http, self.base = http, url.rstrip("/") + "/storage/v1/object/" + BUCKET + "/"
        self._h = {"apikey": service_key, "Authorization": "Bearer " + service_key}

    async def put(self, path: str, data: bytes, ctype: str) -> None:
        r = await self.http.post(self.base + path, content=data, timeout=120,
                                 headers={**self._h, "Content-Type": ctype, "x-upsert": "true", "cache-control": "86400"})
        if r.status_code >= 300:
            raise RuntimeError(f"Storage: HTTP {r.status_code} {r.text[:160]}")

    async def get(self, path: str) -> bytes | None:
        r = await self.http.get(self.base + path, headers=self._h, timeout=120)
        if r.status_code == 200:
            return r.content
        if r.status_code in (400, 404):
            return None
        raise RuntimeError(f"Storage: HTTP {r.status_code}")

    async def remove(self, path: str) -> None:
        await self.http.request("DELETE", self.base + path, headers=self._h, timeout=30)


class Music:
    def __init__(self, storage=None):
        self.st = storage or MemStorage()
        self.index: list[dict] | None = None
        self.cache: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
        self.key = secrets.token_bytes(32)            # assina os links das faixas (muda a cada reinício: a lista é relida)

    def sign(self, fid: str, exp: int) -> str:
        return hmac.new(self.key, f"{fid}|{exp}".encode(), hashlib.sha256).hexdigest()[:32]

    def check(self, fid: str, exp: str, sig: str) -> bool:
        try:
            e = int(exp)
        except (TypeError, ValueError):
            return False
        return e >= time.time() and hmac.compare_digest(self.sign(fid, e), str(sig or ""))

    async def faixas(self) -> list[dict]:
        if self.index is None:
            try:
                raw = await self.st.get("index.json")
                self.index = json.loads(raw.decode()) if raw else []
            except Exception:
                return []                              # sem lista agora: tenta de novo na próxima
        return self.index

    async def _save(self) -> None:
        await self.st.put("index.json", json.dumps(self.index, ensure_ascii=False).encode(), "application/json")

    async def add(self, data: bytes, periodo: str, titulo: str, artista: str = "", fonte: str = "") -> dict:
        if periodo not in PERIODOS:
            raise ValueError("período inválido")
        if not data or len(data) > MAX_BYTES:
            raise ValueError("arquivo vazio ou maior que 25 MB")
        ct = audio_type(data)
        if not ct:
            raise ValueError("o arquivo não é MP3 nem OGG")
        lst = await self.faixas()
        if len(lst) >= MAX_FAIXAS:
            raise ValueError(f"limite de {MAX_FAIXAS} músicas")
        fid = secrets.token_hex(8)
        ext = "mp3" if ct == "audio/mpeg" else "ogg"
        await self.st.put(f"{fid}.{ext}", data, ct)
        item = {"id": fid, "ext": ext, "periodo": periodo, "titulo": clean(titulo) or "lofi", "artista": clean(artista),
                "fonte": clean(fonte, 200), "bytes": len(data), "t": int(time.time())}
        lst.append(item)
        await self._save()
        return item

    async def remove(self, fid: str) -> bool:
        lst = await self.faixas()
        it = next((x for x in lst if x["id"] == fid), None)
        if not it:
            return False
        lst.remove(it)
        await self._save()
        await self.st.remove(f"{fid}.{it['ext']}")
        self.cache.pop(fid, None)
        return True

    async def move(self, fid: str, periodo: str) -> bool:
        if periodo not in PERIODOS:
            raise ValueError("período inválido")
        for it in await self.faixas():
            if it["id"] == fid:
                it["periodo"] = periodo
                await self._save()
                return True
        return False

    async def file(self, fid: str) -> tuple[bytes, str] | None:
        if fid in self.cache:
            self.cache.move_to_end(fid)
            return self.cache[fid]
        it = next((x for x in await self.faixas() if x["id"] == fid), None)
        if not it:
            return None
        data = await self.st.get(f"{fid}.{it['ext']}")
        if not data:
            return None
        v = (data, "audio/mpeg" if it["ext"] == "mp3" else "audio/ogg")
        self.cache[fid] = v
        while len(self.cache) > CACHE_MAX:
            self.cache.popitem(last=False)
        return v

    async def public(self) -> dict:
        exp = int(time.time()) + LINK_TTL
        return {"periodos": PERIODOS,
                "faixas": [{**{k: it.get(k) for k in ("id", "periodo", "titulo", "artista", "fonte")},
                            "src": f"/botlive/musica/{it['id']}?e={exp}&s={self.sign(it['id'], exp)}"} for it in await self.faixas()]}

    async def import_url(self, http, url: str, periodo: str, titulo: str, artista: str = "", fonte: str = "") -> dict:
        """0.32.351: o servidor baixa a faixa direto da Pixabay (só cdn.pixabay.com, https, até 25 MB)."""
        import urllib.parse as up
        u = up.urlparse(str(url or ""))
        if u.scheme != "https" or u.hostname not in IMPORT_HOSTS:
            raise ValueError("só aceito links https de " + ", ".join(IMPORT_HOSTS))
        if any(x.get("fonte") == fonte for x in await self.faixas()) and fonte:
            raise ValueError("essa música já está na lista")
        r = await http.get(url, timeout=120, follow_redirects=False, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            raise ValueError(f"a Pixabay respondeu {r.status_code}")
        return await self.add(r.content, periodo, titulo, artista, fonte)
