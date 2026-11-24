"""System tray, battery alerts and desktop preferences."""

import json
import re
import sys

from PySide6.QtCore import QObject, Property, QSettings, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QActionGroup, QCursor, QDesktopServices, QWindow
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon


PRESETS = {
    "marshall": "Marshall", "individual": "Individual", "bass": "Усиление баса",
    "mid": "Усиление средних", "treble": "Усиление высоких", "mid-reduction": "Ослабление средних",
}
RELEASES = "https://github.com/Benya9669/majorv-desktop/releases"
LATEST_API = "https://api.github.com/repos/Benya9669/majorv-desktop/releases/latest"


class Desktop(QObject):
    changed = Signal()

    def __init__(self, panel, version, settings=None):
        super().__init__()
        self.panel = panel
        self._version = version
        self.settings = settings if settings is not None else QSettings("Major V Desktop", "Major V Desktop")
        self.prefix = "demo/desktop/" if panel.demo else "desktop/"
        self._threshold = self.settings.value(self.prefix + "threshold", 10, type=int)
        self._tray = None
        self._window = None
        self._warning = ""
        self._update = ""
        self._checking = False
        self._new_release = False
        self._network = QNetworkAccessManager(self)
        self._network.finished.connect(self._release_checked)
        self._tray_watch = QTimer(self, interval=3000)
        self._tray_watch.timeout.connect(self._recover_window)
        panel.changed.connect(self._sync)

    version = Property(str, lambda self: self._version, constant=True)
    presets = Property("QVariantList", lambda self: [
        {"value": key, "label": label} for key, label in PRESETS.items()
    ], constant=True)
    threshold = Property(int, lambda self: self._threshold, notify=changed)
    batteryWarning = Property(str, lambda self: self._warning, notify=changed)
    updateStatus = Property(str, lambda self: self._update, notify=changed)
    checking = Property(bool, lambda self: self._checking, notify=changed)
    newRelease = Property(bool, lambda self: self._new_release, notify=changed)

    @Slot(int)
    def setThreshold(self, value):
        if value not in (0, 5, 10, 15, 20) or value == self._threshold:
            return
        self._threshold = value
        self.settings.setValue(self.prefix + "threshold", value)
        self._sync()
        self.changed.emit()

    def attach(self, window):
        self._window = window
        self._tray = QSystemTrayIcon(QApplication.windowIcon(), self)
        self._menu = QMenu()
        self._menu.addAction("Открыть Major V Desktop", self._show)
        self._status = self._menu.addAction("")
        self._status.setEnabled(False)
        self._presets = self._menu.addMenu("Пресет EQ")
        self._actions = {}
        group = QActionGroup(self._presets)
        for key, name in PRESETS.items():
            action = self._presets.addAction(name)
            action.setCheckable(True)
            group.addAction(action)
            action.triggered.connect(lambda checked=False, preset=key: self.panel.setValue("eq", preset))
            self._actions[key] = action
        self._menu.addSeparator()
        self._menu.addAction("Выйти", QApplication.quit)
        # Qt 6.12's native Windows tray menu can crash when a submenu opens.
        # Keep the nested QMenu as a widget on Windows; Linux tray hosts use the exported menu.
        if sys.platform != "win32":
            self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._activated)
        self._tray.messageClicked.connect(self._show)
        self._tray.show()
        window.visibilityChanged.connect(self._visibility)
        self._sync()

    def _activated(self, reason):
        if sys.platform == "win32" and reason == QSystemTrayIcon.ActivationReason.Context:
            self._menu.popup(QCursor.pos())
            self._menu.activateWindow()
        elif reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._show()

    def _show(self):
        self._tray_watch.stop()
        self._window.showNormal()
        self._window.raise_()
        self._window.requestActivate()

    def _visibility(self, visibility):
        if visibility == QWindow.Visibility.Minimized and QSystemTrayIcon.isSystemTrayAvailable():
            self._window.hide()
            self._tray_watch.start()

    def _recover_window(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._show()

    def _sync(self):
        panel = self.panel
        connected = panel.phase in ("connected", "writing")
        if self._tray is not None:
            status = {
                "scanning": "Идёт поиск", "seeking": "Поиск сохранённых Major V",
                "connecting": "Подключение", "waiting": "Ожидаем Major V",
                "disconnecting": "Отключение",
            }.get(panel.phase, "Подключено" if connected else "Нет подключения")
            details = [status]
            if connected and panel.battery >= 0:
                details.append(f"{panel.battery}%")
            if connected and panel.eq in PRESETS:
                details.append(PRESETS[panel.eq])
            summary = " · ".join(details)
            self._status.setText(summary)
            title = "Major V · Демо" if panel.demo else "Major V"
            self._tray.setToolTip(f"{title}\n{summary}")
            self._presets.setEnabled(panel.phase == "connected")
            for key, action in self._actions.items():
                action.setChecked(connected and key == panel.eq)

        warning = ""
        if connected and panel.selectedAddress and 0 <= panel.battery <= 100:
            latch = self.prefix + "low/" + panel.selectedAddress
            notified = self.settings.value(latch, False, type=bool)
            if self._threshold and panel.battery <= self._threshold:
                warning = f"Низкий заряд Major V — {panel.battery}%"
                if not notified:
                    self.settings.setValue(latch, True)
                    if self._tray and QSystemTrayIcon.isSystemTrayAvailable() and self._tray.supportsMessages():
                        self._tray.showMessage("Major V Desktop", warning, QSystemTrayIcon.MessageIcon.Warning)
            elif notified:
                self.settings.remove(latch)
        if self._warning != warning:
            self._warning = warning
            self.changed.emit()

    @Slot()
    def checkUpdates(self):
        if self._checking:
            return
        self._checking = True
        self._new_release = False
        self._update = "Проверяем релизы…"
        self.changed.emit()
        request = QNetworkRequest(QUrl(LATEST_API))
        request.setRawHeader(b"User-Agent", b"Major-V-Desktop")
        request.setTransferTimeout(10000)
        self._network.get(request)

    def _release_checked(self, reply):
        self._checking = False
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if status == 404:
            self._update = "Опубликованных релизов пока нет или репозиторий недоступен."
        elif reply.error() != QNetworkReply.NetworkError.NoError:
            self._update = "Не удалось проверить релизы. Попробуйте позже."
        else:
            try:
                tag = json.loads(bytes(reply.readAll()))["tag_name"]
                if not isinstance(tag, str) or not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
                    raise ValueError
                self._new_release = tuple(map(int, tag[1:].split("."))) > tuple(map(int, self._version.split(".")))
                self._update = f"Доступна версия {tag[1:]}" if self._new_release else "Установлена актуальная версия."
            except (KeyError, ValueError, TypeError):
                self._update = "Не удалось определить версию релиза."
        reply.deleteLater()
        self.changed.emit()

    @Slot()
    def openRelease(self):
        QDesktopServices.openUrl(QUrl(RELEASES + "/latest"))

    def close(self):
        self._tray_watch.stop()
        if self._tray is not None:
            self._tray.hide()
            self._menu.close()
