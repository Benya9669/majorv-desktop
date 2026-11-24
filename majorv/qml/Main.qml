pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

ApplicationWindow {
    id: win
    width: 584
    height: 510
    minimumWidth: 460
    minimumHeight: 400
    visible: true
    title: "Marshall Major V" + (panel.demo ? " · Деморежим" : "")
    DesktopPreferences { id: preferencesDialog; preferences: desktop }
    color: "#20211f"
    palette.window: win.color
    palette.base: "#292a27"
    palette.button: "#30312e"
    readonly property color ink: "#f3f0e8"
    palette.text: win.ink
    palette.windowText: win.ink
    palette.buttonText: win.ink
    palette.highlight: "#e3bf83"
    palette.highlightedText: "#211e18"
    font.family: Qt.platform.os === "windows" ? "Segoe UI" : "Sans Serif"
    font.pixelSize: 14

    readonly property color muted: "#bebcb3"
    readonly property color quiet: "#9e9e95"
    readonly property color rule: "#41423c"
    readonly property bool linked: panel.phase === "connected" || panel.phase === "writing"
    readonly property bool idle: panel.phase === "idle"
    readonly property var presets: desktop.presets
    readonly property var actions: [
        {label: "Без действия", value: "none"},
        {label: "Голосовой помощник", value: "voice"},
        {label: "Эквалайзер", value: "eq"},
        {label: "Spotify", value: "spotify"}
    ]
    readonly property string stateText: ({
        idle: "Нет подключения", scanning: "Поиск наушников…",
        connecting: "Подключение и чтение…", connected: "Подключено",
        waiting: "Ожидаем Major V…", seeking: "Ищем сохранённые Major V…",
        writing: "Применение настройки…", disconnecting: "Отключение…"
    })[panel.phase] || ""

    component Action: Button {
        id: action
        property bool primary: false
        implicitHeight: 36
        leftPadding: 14
        rightPadding: 14
        hoverEnabled: true
        background: Rectangle {
            radius: 5
            color: !action.enabled ? win.palette.base
                 : action.primary ? (action.down ? "#cbaa75" : action.hovered ? "#f1d09a" : win.palette.highlight)
                 : action.down ? "#373832" : action.hovered ? "#41423c" : win.palette.button
            border.width: action.visualFocus ? 2 : 1
            border.color: action.visualFocus ? win.palette.text : action.primary && action.enabled ? color : win.rule
        }
        contentItem: Text {
            text: action.text
            font: action.font
            color: !action.enabled ? win.quiet : action.primary ? win.palette.highlightedText : win.palette.buttonText
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
    }

    component Picker: ComboBox {
        id: picker
        required property string confirmed
        property string emptyText: win.linked ? "Нет данных" : "—"
        signal chosen(string value)
        implicitHeight: 36
        implicitWidth: 200
        leftPadding: 12
        rightPadding: 30
        textRole: "label"
        valueRole: "value"
        property int confirmedIndex: {
            const choices = model || []
            return choices.findIndex(choice => choice[valueRole] === confirmed)
        }
        currentIndex: confirmedIndex
        displayText: confirmedIndex >= 0 ? model[confirmedIndex][textRole] : emptyText
        onActivated: function(index) {
            chosen(model[index][valueRole])
            currentIndex = Qt.binding(() => confirmedIndex)
        }
        contentItem: Text {
            text: picker.displayText
            textFormat: Text.PlainText
            font: picker.font
            color: picker.enabled || picker.confirmedIndex >= 0 ? win.palette.text : win.quiet
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            radius: 5
            color: picker.hovered && picker.enabled ? "#363731" : win.palette.base
            border.color: picker.visualFocus ? win.palette.highlight : win.rule
            border.width: picker.visualFocus ? 2 : 1
        }
        indicator: Canvas {
            x: picker.width - width - 12
            y: (picker.height - height) / 2
            width: 10
            height: 6
            onPaint: {
                const pen = getContext("2d")
                pen.clearRect(0, 0, width, height)
                pen.strokeStyle = win.muted
                pen.lineWidth = 1.5
                pen.beginPath()
                pen.moveTo(1, 1)
                pen.lineTo(5, 5)
                pen.lineTo(9, 1)
                pen.stroke()
            }
        }
        delegate: ItemDelegate {
            id: option
            required property int index
            required property var modelData
            width: ListView.view ? ListView.view.width : picker.width
            height: 38
            leftPadding: 12
            highlighted: picker.highlightedIndex === index
            background: Rectangle { color: option.highlighted ? "#49463c" : win.palette.base }
            contentItem: Text {
                text: option.modelData[picker.textRole]
                textFormat: Text.PlainText
                font: picker.font
                verticalAlignment: Text.AlignVCenter
                color: option.index === picker.confirmedIndex ? win.palette.highlight : win.palette.text
                elide: Text.ElideRight
            }
        }
        popup.background: Rectangle {
            color: win.palette.base
            border.color: win.rule
            radius: 5
        }
    }

    component Divider: Rectangle {
        Layout.fillWidth: true
        implicitHeight: 1
        color: win.rule
    }

    Dialog {
        id: profileDialog
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(440, win.width - 32)
        modal: true
        focus: true
        title: panel.demo ? "Individual EQ · Деморежим" : "Individual EQ"
        padding: 18
        closePolicy: individualProfile.applying ? Popup.NoAutoClose : Popup.CloseOnEscape | Popup.CloseOnPressOutside
        onClosed: individualProfile.cancel()
        onOpened: individualProfile.discover(panel.selectedAddress)
        Connections {
            target: panel
            function onChanged() {
                if (profileDialog.visible && !win.linked && !individualProfile.applying)
                    profileDialog.close()
            }
        }
        background: Rectangle {
            color: "#292a27"
            border.color: win.rule
            radius: 6
        }
        contentItem: ScrollView {
            id: profileScroll
            implicitHeight: Math.min(profileContent.implicitHeight, win.height - 120)
            contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            clip: true
            ColumnLayout {
                id: profileContent
                width: profileScroll.availableWidth
                spacing: 8
                Label {
                    visible: individualProfile.devices.length > 1
                    text: "Выберите наушники для чтения профиля"
                }
                Picker {
                    objectName: "classicPicker"
                    Layout.fillWidth: true
                    visible: individualProfile.devices.length > 1
                    enabled: !individualProfile.busy
                    model: individualProfile.devices
                    confirmed: individualProfile.selectedAddress
                    emptyText: "Выберите Major V"
                    Accessible.name: "Наушники Bluetooth Classic"
                    onChosen: value => individualProfile.read(value)
                }
                Label {
                    visible: individualProfile.busy
                    text: individualProfile.discovering ? "Поиск сопряжённых Major V…" : individualProfile.applying ? "Запись и обратное чтение…" : "Чтение пяти полос…"
                    color: win.muted
                }
                Label {
                    visible: individualProfile.error.length > 0
                    text: individualProfile.error
                    textFormat: Text.PlainText
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    color: "#ffb7a5"
                    Accessible.role: Accessible.AlertMessage
                }
                CurveEditor {
                    Layout.fillWidth: true
                    visible: individualProfile.draft.length === 5
                    profile: individualProfile
                    demo: panel.demo
                    individualActive: panel.eq === "individual" && win.linked
                }
                RowLayout {
                    Layout.fillWidth: true
                    Action {
                        objectName: "readProfileButton"
                        visible: !panel.demo
                        primary: true
                        enabled: !individualProfile.busy
                        text: individualProfile.levels.length ? "Обновить" : "Повторить поиск"
                        onClicked: {
                            if (individualProfile.levels.length)
                                individualProfile.read(individualProfile.selectedAddress)
                            else
                                individualProfile.discover(panel.selectedAddress)
                        }
                    }
                    Item { Layout.fillWidth: true }
                    Action {
                        objectName: "closeProfileButton"
                        enabled: !individualProfile.applying
                        text: "Закрыть"
                        onClicked: profileDialog.close()
                    }
                }
            }
        }
    }

    Dialog {
        id: optionsDialog
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(430, win.width - 32)
        modal: true
        focus: true
        title: "Слоты EQ и таймер"
        padding: 16
        Connections {
            target: panel
            function onChanged() {
                if (optionsDialog.visible && !win.linked)
                    optionsDialog.close()
            }
        }
        background: Rectangle { color: "#292a27"; border.color: win.rule; radius: 6 }
        contentItem: ColumnLayout {
            spacing: 10
            Label { text: "Пресеты M-кнопки"; font.weight: Font.DemiBold }
            Label {
                readonly property var first: win.presets.find(preset => preset.value === panel.slotOne)
                text: "Слот 1 · " + (first ? first.label : "Нет данных")
            }
            Label { text: "Слот 2" }
            Picker {
                objectName: "secondSlotPicker"
                Layout.fillWidth: true
                model: win.presets
                confirmed: panel.slotTwo
                enabled: panel.phase === "connected" && !!panel.activeSlot
                Accessible.name: "Пресет второго слота"
                onChosen: value => panel.setValue("eq_slot2", value)
            }
            Label { text: "Активный слот" }
            Picker {
                objectName: "activeSlotPicker"
                Layout.fillWidth: true
                model: [{label: "Слот 1", value: "1"}, {label: "Слот 2", value: "2"}]
                confirmed: panel.activeSlot
                enabled: panel.phase === "connected" && !!panel.activeSlot
                Accessible.name: "Активный слот EQ"
                onChosen: value => panel.setValue("eq_active_slot", value)
            }
            Divider {}
            Label { text: "Выключение без подключения"; font.weight: Font.DemiBold }
            Picker {
                objectName: "timerPicker"
                Layout.fillWidth: true
                model: ["15", "20"].map(value => ({label: value + " мин", value: value}))
                confirmed: panel.timerMinutes
                emptyText: panel.timerMinutes ? panel.timerMinutes + " мин" : "Нет данных"
                enabled: panel.phase === "connected" && !!panel.timerMinutes
                Accessible.name: "Таймер без подключения"
                onChosen: value => panel.setValue("timer", value)
            }
            Label {
                visible: !!panel.error
                text: panel.error
                textFormat: Text.PlainText
                color: "#ffb7a5"
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }
            Action {
                objectName: "closeSlotTimerButton"
                Layout.alignment: Qt.AlignRight
                text: "Закрыть"
                onClicked: optionsDialog.close()
            }
        }
    }

    ScrollView {
        id: scroll
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ColumnLayout {
            width: scroll.availableWidth
            spacing: 0

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 88
                color: "#171816"
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 24
                    anchors.rightMargin: 24
                    spacing: 12
                    Label {
                        text: "Major V"
                        font.pixelSize: 36
                        font.weight: Font.DemiBold
                        font.letterSpacing: -1
                    }
                    Rectangle {
                        visible: panel.demo
                        implicitWidth: demoText.implicitWidth + 16
                        implicitHeight: 24
                        radius: 4
                        color: "#3b3326"
                        Label {
                            id: demoText
                            anchors.centerIn: parent
                            text: "Деморежим"
                            font.pixelSize: 12
                            color: win.palette.highlight
                        }
                    }
                    Item { Layout.fillWidth: true }
                    ColumnLayout {
                        spacing: 2
                        Label {
                            text: "Заряд"
                            font.pixelSize: 12
                            color: desktop.batteryWarning.length ? "#efc588" : win.muted
                            Layout.alignment: Qt.AlignRight
                        }
                        RowLayout {
                            spacing: 7
                            Rectangle {
                                width: 23
                                height: 12
                                radius: 2
                                color: "transparent"
                                border.color: win.quiet
                                Rectangle {
                                    x: 2; y: 2
                                    height: 8
                                    width: panel.battery >= 0 ? 19 * panel.battery / 100 : 0
                                    color: win.palette.highlight
                                }
                                Rectangle { x: 23; y: 4; width: 2; height: 4; color: win.quiet }
                            }
                            Label {
                                objectName: "batteryLabel"
                                text: panel.battery >= 0 ? panel.battery + "%" : "—"
                                font.pixelSize: 19
                                font.weight: Font.DemiBold
                            }
                        }
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.margins: 24
                spacing: 12
                RowLayout {
                    spacing: 8
                    Rectangle {
                        width: 8; height: 8; radius: 4
                        color: win.linked ? "#b4cc92" : win.idle ? win.quiet : win.palette.highlight
                    }
                    Label {
                        objectName: "connectionStatus"
                        text: win.stateText
                        color: win.muted
                    }
                    Item { Layout.fillWidth: true }
                    Action {
                        objectName: "scanButton"
                        text: panel.phase === "scanning" ? "Идёт поиск…" : win.idle ? "Найти наушники" : "Выбрать другие"
                        primary: win.idle && !panel.devices.length
                        enabled: ["idle", "connected", "waiting", "seeking", "connecting"].includes(panel.phase)
                        onClicked: win.idle ? panel.scan() : panel.chooseOther()
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Picker {
                        objectName: "devicePicker"
                        Layout.fillWidth: true
                        model: panel.devices
                        textRole: "label"
                        valueRole: "address"
                        confirmed: panel.selectedAddress
                        emptyText: "Выберите устройство"
                        enabled: win.idle && count > 0
                        Accessible.name: "Устройство Bluetooth"
                        onChosen: value => panel.selectDevice(value)
                    }
                    Action {
                        objectName: "connectionButton"
                        primary: !win.linked
                        text: win.linked || panel.phase === "disconnecting" ? "Отключить" : "Подключить"
                        enabled: ((win.idle || panel.phase === "waiting") && panel.selectedAddress !== "") || panel.phase === "connected"
                        onClicked: win.linked ? panel.disconnectDevice() : panel.connectDevice()
                    }
                }
                Label {
                    objectName: "errorMessage"
                    Layout.fillWidth: true
                    visible: panel.error !== ""
                    text: panel.error
                    textFormat: Text.PlainText
                    color: "#ffb7a5"
                    wrapMode: Text.Wrap
                    Accessible.role: Accessible.AlertMessage
                }
                Label {
                    visible: desktop.batteryWarning.length > 0
                    text: desktop.batteryWarning
                    color: "#efc588"
                }
                Divider { Layout.topMargin: 6; Layout.bottomMargin: 4 }
                RowLayout {
                    Layout.fillWidth: true
                    Label {
                        Layout.fillWidth: true
                        text: "Настройки"
                        font.pixelSize: 21
                        font.weight: Font.DemiBold
                    }
                    Action {
                        objectName: "preferencesButton"
                        text: "Параметры"
                        onClicked: preferencesDialog.open()
                    }
                    Action {
                        objectName: "slotTimerButton"
                        text: "Слоты EQ и таймер"
                        enabled: panel.phase === "connected"
                        onClicked: optionsDialog.open()
                    }
                }
                GridLayout {
                    Layout.fillWidth: true
                    columns: 2
                    rowSpacing: 9
                    columnSpacing: 12
                    Label { text: "Пресет EQ"; Layout.fillWidth: true }
                    Picker {
                        objectName: "eqPicker"
                        Layout.preferredWidth: 205
                        model: win.presets
                        confirmed: panel.eq
                        enabled: panel.phase === "connected"
                        Accessible.name: "Пресет EQ"
                        onChosen: value => panel.setValue("eq", value)
                    }
                    Label { text: "M-кнопка" }
                    Picker {
                        objectName: "mButtonPicker"
                        Layout.preferredWidth: 205
                        model: win.actions
                        confirmed: panel.mButton
                        enabled: panel.phase === "connected"
                        Accessible.name: "Назначение M-кнопки"
                        onChosen: value => panel.setValue("m_button", value)
                    }
                    Label { text: "Звуковые подсказки" }
                    Picker {
                        objectName: "promptsPicker"
                        Layout.preferredWidth: 205
                        model: [{label: "Включены", value: "on"}, {label: "Выключены", value: "off"}]
                        confirmed: panel.prompts
                        enabled: panel.phase === "connected"
                        Accessible.name: "Звуковые подсказки"
                        onChosen: value => panel.setValue("prompts", value)
                    }
                }
                GridLayout {
                    Layout.fillWidth: true
                    columns: !panel.demo || scroll.availableWidth - 48 >= profileButton.implicitWidth + lossButton.implicitWidth + columnSpacing ? 2 : 1
                    Action {
                        id: profileButton
                        objectName: "profileButton"
                        text: "Полосы Individual EQ"
                        enabled: panel.phase === "connected"
                        onClicked: profileDialog.open()
                    }
                    Action {
                        id: lossButton
                        objectName: "demoLossButton"
                        Layout.alignment: Qt.AlignRight
                        visible: panel.demo && win.linked
                        enabled: panel.phase === "connected"
                        text: "Имитировать потерю связи"
                        onClicked: panel.simulateLoss()
                    }
                }
            }
        }
    }
}
