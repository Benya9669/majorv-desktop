import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Dialog {
    id: dialog
    required property var preferences
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(400, parent.width - 32)
    modal: true
    title: "Параметры приложения"
    padding: 18
    standardButtons: Dialog.Close
    Component.onCompleted: standardButton(Dialog.Close).text = "Закрыть"
    contentItem: ColumnLayout {
        spacing: 10
        Label { text: "Предупреждение о низком заряде" }
        ComboBox {
            id: threshold
            objectName: "thresholdPicker"
            Layout.fillWidth: true
            Accessible.name: "Порог предупреждения о заряде"
            model: ["Выключено", "5%", "10%", "15%", "20%"]
            currentIndex: [0, 5, 10, 15, 20].indexOf(dialog.preferences.threshold)
            onActivated: i => dialog.preferences.setThreshold([0, 5, 10, 15, 20][i])
        }
        Rectangle { Layout.fillWidth: true; Layout.topMargin: 6; implicitHeight: 1; color: "#41423c" }
        Label { text: "Major V Desktop · " + dialog.preferences.version }
        Label {
            Layout.fillWidth: true
            visible: text.length > 0
            text: dialog.preferences.updateStatus
            wrapMode: Text.Wrap
        }
        Button {
            text: dialog.preferences.newRelease ? "Скачать обновление" : "Проверить обновления"
            enabled: !dialog.preferences.checking
            onClicked: dialog.preferences.newRelease ? dialog.preferences.openRelease() : dialog.preferences.checkUpdates()
        }
    }
}
