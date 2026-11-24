"""Collect QML modules used by the panel and Qt Quick's Basic style."""

from pathlib import PurePosixPath

from PyInstaller.utils.hooks.qt import add_qt6_dependencies, pyside6_library_info

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
qml_binaries, qml_datas = pyside6_library_info.collect_qtqml_files()
modules = {
    "QtCore", "QtQml", "QtQml/Models", "QtQml/WorkerScript", "QtQuick",
    "QtQuick/Layouts", "QtQuick/Window", "QtQuick/Shapes", "QtQuick/Templates",
    "QtQuick/Controls", "QtQuick/Controls/impl", "QtQuick/Controls/Basic",
    "QtQuick/Controls/Basic/impl",
}


def uses_module(entry):
    destination = PurePosixPath(entry[1].replace("\\", "/"))
    relative = destination.parts[destination.parts.index("qml") + 1:]
    return "/".join(relative) in modules


binaries += [entry for entry in qml_binaries if uses_module(entry)]
datas += [entry for entry in qml_datas if uses_module(entry)]
