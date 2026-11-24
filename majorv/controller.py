"""Qt owns the view state; one asyncio thread owns the Bluetooth session."""

import asyncio
import logging
import threading

from PySide6.QtCore import QObject, Property, QSettings, QTimer, Signal, Slot

from .backend import BleBackend, DemoBackend


class Session(QObject):
    completed = Signal(int, str, object, str)
    lost = Signal(int)
    updated = Signal(int, object)

    def __init__(self, backend):
        super().__init__()
        self.backend = backend
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, name="Major V Bluetooth", daemon=True)
        self.thread.start()
        self.ready.wait()

    def _run(self):
        with asyncio.Runner() as runner:
            self.loop = runner.get_loop()
            self.lock = asyncio.Lock()
            self.stopping = asyncio.Event()
            self.pending = set()
            self.ready.set()
            runner.run(self.stopping.wait())
            runner.run(self._shutdown())

    def submit(self, session, operation, *args):
        self.loop.call_soon_threadsafe(self._schedule, session, operation, args)

    def cancel_pending(self):
        self.loop.call_soon_threadsafe(self._cancel_pending)

    def _cancel_pending(self):
        for task in self.pending:
            task.cancel()

    def _schedule(self, session, operation, args):
        task = self.loop.create_task(self._execute(session, operation, args))
        self.pending.add(task)
        task.add_done_callback(self.pending.discard)

    async def _execute(self, session, operation, args):
        async with self.lock:
            result = None
            error = ""
            try:
                async with asyncio.timeout(75 if operation == "connecting" else 45):
                    if operation in ("scanning", "seeking"):
                        if operation == "scanning":
                            await self.backend.disconnect()
                        result = await self.backend.scan()
                    elif operation == "connecting":
                        await self.backend.connect(args[0], lambda: self.lost.emit(session))
                        await self.backend.subscribe(lambda fields: self.updated.emit(session, fields))
                        result = await self.backend.read()
                    elif operation == "refresh":
                        result = await self.backend.read()
                    elif operation == "writing":
                        key, value = args
                        try:
                            await self.backend.set_value(key, value)
                        except Exception as exc:
                            error = f"Не удалось изменить настройку. {exc}"
                        result = await self.backend.read()
                        if result.get(key) != value and not error:
                            error = "Наушники не подтвердили изменение. Показаны считанные значения."
                    elif operation == "disconnecting":
                        await self.backend.disconnect()
            except Exception as exc:
                detail = str(exc) or type(exc).__name__
                error = {
                    "scanning": "Поиск не удался. Проверьте Bluetooth в настройках системы.",
                    "seeking": "Не удалось найти сохранённые наушники.",
                    "refresh": "Связь с Major V потеряна.",
                    "connecting": "Не удалось подключиться и прочитать настройки. Проверьте сопряжение.",
                    "writing": "Связь прервана или настройки недоступны. Подключитесь снова.",
                    "disconnecting": "Не удалось завершить соединение.",
                }[operation] + " " + detail
                if operation in ("connecting", "writing", "refresh"):
                    await self._release()
                elif operation == "disconnecting":
                    # A failed disconnect can leave the device connected and usable.
                    try:
                        async with asyncio.timeout(5):
                            result = await self.backend.read()
                    except Exception:
                        await self._release()
            self.completed.emit(session, operation, result, error)

    async def _release(self):
        try:
            async with asyncio.timeout(4):
                await self.backend.disconnect()
        except Exception:
            logging.exception("Bluetooth disconnect failed")

    async def _shutdown(self):
        # Cancel our pending operations, leaving OS transport tasks alive for disconnect().
        pending = list(self.pending)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await self._release()

    def close(self):
        self.loop.call_soon_threadsafe(self.stopping.set)
        self.thread.join(timeout=6)


class Panel(QObject):
    changed = Signal()

    def __init__(self, demo=False, *, settings=None, backend=None):
        super().__init__()
        self._demo = demo
        self._session = 0
        self._phase = "idle"
        self._devices = []
        self._address = ""
        self._values = {}
        self._error = ""
        self._settings = settings if settings is not None else (
            None if demo else QSettings("Major V Desktop", "Major V Desktop")
        )
        self._remembered = self._settings.value("bluetooth/address", "", type=str) if self._settings else ""
        self._retry_ms = 2000
        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(self._seek)
        self._poll = QTimer(self)
        self._poll.setInterval(20000)
        self._poll.timeout.connect(self._refresh)
        self._poll_pending = False
        self.worker = Session(backend or (DemoBackend() if demo else BleBackend()))
        self.worker.completed.connect(self._complete)
        self.worker.lost.connect(self._lost)
        self.worker.updated.connect(self._apply_updates)
        if self._remembered:
            self._address = self._remembered
            self._phase = "waiting"
            self._retry.start(0)

    demo = Property(bool, lambda self: self._demo, constant=True)
    phase = Property(str, lambda self: self._phase, notify=changed)
    devices = Property("QVariantList", lambda self: self._devices, notify=changed)
    selectedAddress = Property(str, lambda self: self._address, notify=changed)
    error = Property(str, lambda self: self._error, notify=changed)
    eq = Property(str, lambda self: self._values.get("eq") or "", notify=changed)
    mButton = Property(str, lambda self: self._values.get("m_button") or "", notify=changed)
    prompts = Property(str, lambda self: self._values.get("prompts") or "", notify=changed)
    slotOne = Property(str, lambda self: self._values.get("eq_slot1") or "", notify=changed)
    slotTwo = Property(str, lambda self: self._values.get("eq_slot2") or "", notify=changed)
    activeSlot = Property(str, lambda self: self._values.get("eq_active_slot") or "", notify=changed)
    timerMinutes = Property(str, lambda self: self._values.get("timer") or "", notify=changed)

    @Property(int, notify=changed)
    def battery(self):
        level = self._values.get("battery")
        return level if level is not None else -1

    def _begin(self, operation, *args):
        self._phase = operation
        self._error = ""
        self.changed.emit()
        self.worker.submit(self._session, operation, *args)

    def _seek(self):
        if self._remembered and self._phase == "waiting":
            self._begin("seeking")

    def _refresh(self):
        if self._phase == "connected" and not self._poll_pending:
            self._poll_pending = True
            self.worker.submit(self._session, "refresh")

    @Slot(int, object)
    def _apply_updates(self, session, fields):
        if session == self._session and self._phase == "connected":
            self._values.update(fields)
            self.changed.emit()

    def _remember(self, address):
        if self._remembered == address:
            return
        self._remembered = address
        if self._settings is not None:
            if address:
                self._settings.setValue("bluetooth/address", address)
            else:
                self._settings.remove("bluetooth/address")

    def _wait_for_device(self):
        self._phase = "waiting"
        self._values = {}
        self._poll_pending = False
        self._poll.stop()
        self._retry.start(self._retry_ms)
        self._retry_ms = min(30000, self._retry_ms * 2)

    @Slot()
    def chooseOther(self):
        self._remember("")
        self._retry.stop()
        self._poll.stop()
        self._poll_pending = False
        self._session += 1
        self.worker.cancel_pending()
        self._values = {}
        self._devices = []
        self._address = ""
        self._begin("scanning")

    @Slot()
    def scan(self):
        if self._phase == "idle":
            self._begin("scanning")

    @Slot(str)
    def selectDevice(self, address):
        if self._phase == "idle" and any(d["address"] == address for d in self._devices):
            self._address = address
            self.changed.emit()

    @Slot()
    def connectDevice(self):
        if self._phase in ("idle", "waiting") and self._address:
            self._retry.stop()
            self._session += 1
            self._begin("connecting", self._address)

    @Slot()
    def disconnectDevice(self):
        if self._phase == "connected":
            self._poll.stop()
            self._begin("disconnecting")

    @Slot(str, str)
    def setValue(self, key, value):
        if self._phase == "connected" and self._values.get(key) != value:
            self._begin("writing", key, value)

    @Slot()
    def simulateLoss(self):
        if self._demo and self._phase == "connected":
            self.worker.loop.call_soon_threadsafe(self.worker.backend.simulate_loss)

    @Slot(int)
    def _lost(self, session):
        if session != self._session or self._phase not in ("connecting", "connected", "writing"):
            return
        self._session += 1  # Ignore any result arriving after the disconnect callback.
        self._values = {}
        self._phase = "idle"
        self._error = "Связь с Major V потеряна."
        if self._remembered == self._address:
            self._wait_for_device()
        self.changed.emit()

    @Slot(int, str, object, str)
    def _complete(self, session, operation, result, error):
        if session != self._session:
            return
        if operation == "refresh":
            self._poll_pending = False
            if result is None:
                self._lost(session)
            else:
                self._apply_updates(session, result)
            return
        self._error = error
        self._phase = "idle"
        if operation == "seeking":
            if result and self._remembered in result:
                self._devices = [{"address": self._remembered, "label": result[self._remembered]}]
                self.connectDevice()
                return
            self._wait_for_device()
        elif operation == "scanning":
            names = result or {}
            self._devices = [
                {"address": address, "label": f"{name} · {address}"}
                for address, name in names.items()
            ]
            if self._address not in names:
                self._address = next(iter(names), "")
            if not names and not error:
                self._error = "Major V не найдены. Включите наушники и повторите поиск."
        elif result is not None:
            self._values = result
            self._phase = "connected"
            self._remember(self._address)
            self._retry_ms = 2000
            self._poll.start()
        else:
            self._values = {}
            if operation != "disconnecting" and self._remembered == self._address:
                self._wait_for_device()
        self.changed.emit()

    def close(self):
        self._retry.stop()
        self._poll.stop()
        self._session += 1
        self.worker.close()
