"""Edit local profiles and apply verified Individual EQ settings through the CLI."""

import json
import re
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Property, QProcess, QSettings, Signal, Slot

from scripts.individual_eq_apply import curve_positions, supports_curve
from scripts.individual_eq_dsp import slider_gain_hundredths


def valid_address(address):
    return (isinstance(address, str) and address != "00:00:00:00:00:00"
            and re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", address) is not None)


class IndividualProfile(QObject):
    changed = Signal()

    def __init__(self, demo=False, parent=None, *, settings=None):
        super().__init__(parent)
        self._demo = demo
        self._process = None
        self._levels = []
        self._error = ""
        self._devices = []
        self._address = ""
        self._discovering = False
        self._applying = False
        self._unconfirmed = set()
        self._draft = []
        self._undo = []
        self._demo_levels = [0.0] * 5
        self._notice = ""
        self._settings = settings if settings is not None else QSettings("Major V Desktop", "Major V Desktop")

    busy = Property(bool, lambda self: self._process is not None, notify=changed)
    levels = Property("QVariantList", lambda self: self._levels, notify=changed)
    error = Property(str, lambda self: self._error, notify=changed)
    devices = Property("QVariantList", lambda self: self._devices, notify=changed)
    selectedAddress = Property(str, lambda self: self._address, notify=changed)
    discovering = Property(bool, lambda self: self._discovering, notify=changed)
    applying = Property(bool, lambda self: self._applying, notify=changed)
    draft = Property("QVariantList", lambda self: self._draft, notify=changed)
    notice = Property(str, lambda self: self._notice, notify=changed)
    canUndo = Property(bool, lambda self: bool(self._undo) and self._undo != self._draft, notify=changed)
    supported = Property(bool, lambda self: self._demo or supports_curve(self._draft), notify=changed)
    dirty = Property(bool, lambda self: self._draft != self._levels, notify=changed)
    needsApply = Property(bool, lambda self: bool(self._levels) and
                          (self.dirty or self._address in self._unconfirmed), notify=changed)

    @Property("QStringList", notify=changed)
    def profileNames(self):
        self._settings.beginGroup("individualProfiles")
        try:
            names = []
            for key in self._settings.childKeys():
                try:
                    names.append(bytes.fromhex(key).decode())
                except ValueError:
                    continue
            return sorted(names, key=str.casefold)
        finally:
            self._settings.endGroup()

    @Slot(int, int)
    def edit(self, band, position):
        if self.busy or len(self._draft) != 5 or not 0 <= band < 5 or not 0 <= position <= 100:
            return
        if self._levels == self._draft:
            self._undo = self._draft.copy()
        self._draft[band] = (position - 50) * 12 / 100
        self._notice = self._error = ""
        self.changed.emit()

    @Slot(str)
    def saveNamed(self, name):
        name = name.strip()
        if not name or len(name) > 60 or self.busy or len(self._draft) != 5:
            return
        self._settings.setValue("individualProfiles/" + name.encode().hex(), json.dumps(self._draft))
        self._settings.sync()
        if self._settings.status() != QSettings.Status.NoError:
            self._error = "Не удалось сохранить профиль на компьютере."
        else:
            self._notice = f"Профиль «{name}» сохранён на компьютере."
            self._error = ""
        self.changed.emit()

    @Slot(str)
    def loadNamed(self, name):
        if self.busy or not self._levels:
            return
        try:
            levels = json.loads(self._settings.value("individualProfiles/" + name.encode().hex(), "null"))
            if not valid_levels(levels):
                raise ValueError
        except (ValueError, TypeError):
            self._error = "Не удалось загрузить сохранённую кривую."
        else:
            self._undo = self._draft.copy()
            self._draft = list(levels)
            self._notice = f"Загружен профиль «{name}»."
            self._error = ""
        self.changed.emit()

    @Slot()
    def undo(self):
        if self.canUndo and not self.busy:
            self._draft, self._undo = self._undo, []
            self._notice = self._error = ""
            self.changed.emit()

    @Slot()
    def apply(self):
        if self.busy or not self.needsApply or not self.supported:
            return
        self._undo = self._levels.copy()
        self._notice = self._error = ""
        if self._demo:
            self._demo_levels = self._draft.copy()
            self._levels = self._demo_levels.copy()
            self._notice = "Демопрофиль применён."
            self.changed.emit()
            return
        self._applying = True
        self._start("apply", self._address, "--bands", *(str(g) for g in self._draft), "--expect",
                    *(str(round(g * 100)) for g in self._levels))

    @Slot(str)
    def discover(self, ble_address):
        if self._applying:
            return
        self.cancel()
        if self._demo:
            self.read("")
            return
        self._discovering = True
        self._start("devices", "--ble-address", ble_address)

    @Slot(str)
    def read(self, address):
        if self._applying:
            return
        self._stop()
        if self._demo:
            self._levels = self._demo_levels.copy()
            self._draft = self._levels.copy()
            self.changed.emit()
            return
        address = address.strip()
        if not valid_address(address):
            self._error = "Не удалось определить устройство. Повторите поиск."
            self.changed.emit()
            return
        self._address = address
        self._start("read", address)

    def _start(self, *arguments):
        process = QProcess(self)
        self._process = process
        process.started.connect(self._started)
        process.finished.connect(self._finished)
        process.errorOccurred.connect(self._process_error)
        if getattr(sys, "frozen", False):
            name = "majorv-eq.exe" if sys.platform == "win32" else "majorv-eq"
            process.start(str(Path(sys.executable).with_name(name)), [*arguments, "--json"])
        else:
            script = Path(__file__).resolve().parents[1] / "scripts/individual_eq.py"
            process.start(sys.executable, ["-X", "utf8", str(script), *arguments, "--json"])
        self.changed.emit()

    @Slot()
    def _started(self):
        process = self.sender()
        if self._process is not process:
            process.kill()

    @Slot(int, QProcess.ExitStatus)
    def _finished(self, code, status):
        process = self.sender()
        process.deleteLater()
        if self._process is not process:
            return
        self._process = None
        discovery = self._discovering
        self._discovering = False
        applying, self._applying = self._applying, False
        if code == 0 and status == QProcess.ExitStatus.NormalExit:
            try:
                result = json.loads(bytes(process.readAllStandardOutput()))
                if discovery:
                    self._found_devices(result)
                else:
                    if not valid_levels(result):
                        raise ValueError
                    if applying:
                        expected = [slider_gain_hundredths(p) / 100 for p in curve_positions(self._draft)]
                        if result != expected:
                            raise ValueError
                    self._levels = [float(gain) for gain in result]
                    self._draft = self._levels.copy()
                    if applying:
                        self._unconfirmed.discard(self._address)
                        self._notice = "Сохранено. Пять полос и коэффициенты DSP подтверждены чтением."
                    elif self._address in self._unconfirmed:
                        self._notice = "Усиления прочитаны. Нажмите «Применить», чтобы повторить полную запись и проверку."
            except ValueError:
                self._error = ("Не удалось разобрать результат поиска Bluetooth." if discovery
                               else "Наушники вернули неизвестный формат профиля.")
        else:
            details = bytes(process.readAllStandardError()).decode("utf-8", errors="replace").strip().splitlines()
            if applying:
                self._error = ""
            elif discovery:
                self._error = "Не удалось получить список устройств Bluetooth."
            else:
                self._error = "Не удалось прочитать Individual EQ. Включите наушники и повторите поиск."
            if details:
                self._error = (self._error + " " + details[-1]).strip()
        if applying and (code != 0 or status != QProcess.ExitStatus.NormalExit or self._error):
            self._unconfirmed.add(self._address)
            self._draft = self._levels = self._undo = []
            self._error = ("Сохранение не подтверждено. Перечитайте профиль. " + self._error).rstrip()
        self.changed.emit()

    def _found_devices(self, names):
        if not isinstance(names, dict) or not all(
            valid_address(addr) and isinstance(name, str) for addr, name in names.items()
        ):
            raise ValueError
        self._devices = [{"value": addr, "label": f"{name} · {addr}"} for addr, name in names.items()]
        if len(names) == 1:
            self.read(next(iter(names)))
        elif not names:
            self._error = ("Сопряжённые Major V не найдены. Подключите наушники для воспроизведения "
                           "звука в настройках Bluetooth и повторите поиск.")

    @Slot(QProcess.ProcessError)
    def _process_error(self, reason):
        if reason == QProcess.ProcessError.FailedToStart:
            process = self.sender()
            process.deleteLater()
            if self._process is process:
                self._process = None
                self._discovering = False
                self._applying = False
                self._error = "Не удалось запустить обмен с наушниками. " + process.errorString()
                self.changed.emit()

    def _stop(self):
        process, self._process = self._process, None
        if process is not None:
            process.kill()
        self._error = ""
        self._levels = []
        self._draft = []
        self._undo = []
        self._notice = ""
        self._discovering = False

    @Slot()
    def cancel(self):
        if self._applying:
            return
        self._stop()
        self._devices = []
        self._address = ""
        self.changed.emit()

    def close(self):
        if self._applying and self._process is not None:
            self._process.waitForFinished(45000)
            self._applying = False
        self.cancel()
        for process in self.findChildren(QProcess):
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
                process.waitForFinished(1000)


def valid_levels(levels):
    return isinstance(levels, list) and len(levels) == 5 and all(
        type(gain) in (int, float) and -6 <= gain <= 6 for gain in levels
    )
