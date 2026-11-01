"""0.32.121: a porta abre antes da carga e o /health conta onde a subida está. Sem internet."""
import asyncio
import time

from app.hub import PumpHub


def _hub():
    h = PumpHub.__new__(PumpHub)
    return h


def test_boot_says_ready():
    h = _hub()

    async def start():
        h._step("sombras")
    h.start = start
    asyncio.run(h.boot())
    b = h.boot_status()
    assert b["etapa"] == "pronto" and b["erro"] is None and b["carregando"] is False


def test_failed_boot_stays_up_and_shows_only_the_error_type():
    h = _hub()

    async def start():
        h._step("calls")
        raise ValueError("senha=segredo")
    h.start = start
    asyncio.run(h.boot())
    b = h.boot_status()
    assert b["etapa"] == "calls" and b["erro"] == "ValueError" and "segredo" not in str(b)


def test_status_counts_time_while_loading():
    h = _hub()
    h.boot_info = {"etapa": "contas", "inicio": time.time() - 30, "carregando": True}
    b = h.boot_status()
    assert b["carregando"] is True and b["segundos"] >= 29


def test_stop_during_load_does_not_overwrite_saved_data():
    h = _hub()
    h.monitor, h._tasks, h.engines = None, [], {}
    h.boot_info = {"carregando": True}
    salvou = []

    async def save():
        salvou.append(1)
    h.save_ghosts = h.save_lab = save
    asyncio.run(h.stop())
    assert salvou == []
    h.boot_info = {"carregando": False}
    asyncio.run(h.stop())
    assert salvou == [1, 1]
