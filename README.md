# Major V Desktop

Рабочая основа приложения для управления наушниками Marshall Major V в Windows и Linux. Сейчас доступен консольный BLE-клиент. Для графического интерфейса выбран Python с PySide6 и QML. Реализация интерфейса и подключения по Bluetooth Classic — следующие этапы.

## Начало работы

Установите Python 3.11 или новее и создайте виртуальное окружение из корня проекта.

**Windows (PowerShell)**

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python scripts/majorv_client.py --help
```

**Linux**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/majorv_client.py --help
```

Для проверки с наушниками выполните сопряжение в настройках Bluetooth ОС. В командах выше замените `--help` на `--name "Major V" status`, чтобы прочитать заряд и настройки. Если рядом несколько устройств с похожими именами, используйте `--address` с адресом нужного устройства.

## Что проверено

В предыдущих опытах на Major V воспроизведены смена пресета (`eq`), назначение M-кнопки (`m-button`) и переключение звуковых подсказок (`prompts`). Экспериментальная команда `timer` учитывает только `--not-connected`, хотя CLI требует также `--connected-paused`.

## С чего продолжить на другом ПК

1. Прочитать [разбор Individual EQ](docs/individual-eq.md). Там описаны параметры пяти полос, формат сообщений и проверка по захвату.
2. Проверить подключение к сервису Airoha по его UUID на каждой ОС через `QBluetoothSocket` и прочитать текущий профиль. В приложении понадобятся оба соединения — BLE для основных настроек и RFCOMM для Individual.
3. Проверить расчёт коэффициентов по эталонным данным, затем проверить изменение одной полосы и чтение значения после переподключения. Эти проверки нужны перед добавлением редактора Individual в UI.
