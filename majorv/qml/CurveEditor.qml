import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ColumnLayout {
    id: editor
    required property var profile
    required property bool demo
    required property bool individualActive
    spacing: 7

    Row {
        id: bands
        Layout.fillWidth: true
        spacing: 4
        Repeater {
            model: ["160 Гц", "400 Гц", "1 кГц", "2,5 кГц", "6,25 кГц"]
            Column {
                id: band
                required property int index
                required property string modelData
                width: (bands.width - 4 * bands.spacing) / 5
                spacing: 4
                Label {
                    text: band.modelData
                    anchors.horizontalCenter: parent.horizontalCenter
                }
                Slider {
                    id: slider
                    objectName: "eqBand" + band.index
                    anchors.horizontalCenter: parent.horizontalCenter
                    height: 88
                    orientation: Qt.Vertical
                    from: 0
                    to: 100
                    stepSize: 1
                    snapMode: Slider.SnapAlways
                    value: 50 + Math.round((editor.profile.draft[band.index] ?? 0) / 0.12)
                    Accessible.name: "Усиление " + band.modelData
                    enabled: !editor.profile.busy
                    onMoved: editor.profile.edit(band.index, Math.round(value))
                }
                Label {
                    anchors.horizontalCenter: parent.horizontalCenter
                    readonly property real gain: editor.profile.draft[band.index] ?? 0
                    text: (gain > 0 ? "+" : "") + gain.toLocaleString(Qt.locale("ru_RU"), "f", 2) + " дБ"
                    color: palette.highlight
                }
            }
        }
    }

    ComboBox {
        id: library
        objectName: "curveLibrary"
        visible: count > 0
        enabled: !editor.profile.busy
        Layout.fillWidth: true
        model: editor.profile.profileNames
        currentIndex: -1
        displayText: "Загрузить сохранённый профиль"
        Accessible.name: displayText
        onActivated: function(index) {
            nameField.text = textAt(index)
            editor.profile.loadNamed(nameField.text)
        }
    }
    RowLayout {
        TextField {
            id: nameField
            objectName: "curveName"
            Layout.fillWidth: true
            placeholderText: "Имя профиля на компьютере"
            placeholderTextColor: "#aaa89e"
            Accessible.name: placeholderText
            maximumLength: 60
            enabled: !editor.profile.busy
        }
        Button {
            objectName: "saveCurve"
            text: editor.profile.profileNames.indexOf(nameField.text.trim()) < 0 ? "Сохранить" : "Обновить профиль"
            enabled: nameField.text.trim().length > 0 && !editor.profile.busy
            onClicked: editor.profile.saveNamed(nameField.text)
        }
    }
    Label {
        visible: !editor.demo && editor.profile.needsApply && (!editor.profile.supported || !editor.individualActive)
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        text: !editor.profile.supported
              ? "Для записи задайте усиление каждой полосы ползунком."
              : "Для применения выберите пресет Individual на главном экране."
    }
    Label {
        visible: editor.profile.notice.length > 0
        text: editor.profile.notice
        textFormat: Text.PlainText
        Layout.fillWidth: true
        wrapMode: Text.Wrap
    }
    RowLayout {
        Button {
            objectName: "applyCurve"
            text: editor.profile.applying ? "Сохранение…" : "Применить"
            enabled: !editor.profile.busy && editor.profile.needsApply && editor.profile.supported
                     && (editor.demo || editor.individualActive)
            onClicked: editor.profile.apply()
        }
        Button {
            objectName: "undoCurve"
            text: "Отменить"
            enabled: !editor.profile.busy && editor.profile.canUndo
            onClicked: editor.profile.undo()
        }
    }
}
