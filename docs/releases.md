# Установка и обновление

Готовые пакеты появляются в [GitHub Releases](https://github.com/Benya9669/majorv-desktop/releases) после публикации версии. Для установки из пакета Python и pip не нужны.

**Windows x64.** Скачайте `majorv-desktop-X.Y.Z-windows-x64.exe` и запустите установщик. Приложение появится в меню «Пуск». Установка выполняется для текущего пользователя. У опубликованных этой сборкой установщиков нет подписи Authenticode.

**Ubuntu 24.04 и совместимые более новые системы amd64.** Скачайте `majorv-desktop_X.Y.Z_amd64.deb` и откройте его системным установщиком пакетов. Другой способ — `sudo apt install ./majorv-desktop_X.Y.Z_amd64.deb` из каталога с загрузкой. Приложение появится в меню программ. Для связи с наушниками нужен работающий BlueZ.

Для обновления закройте приложение и установите пакет следующей версии поверх предыдущего. Профили и настройки хранятся отдельно от программы в хранилище текущего пользователя Qt (HKCU в Windows, пользовательский каталог конфигурации в Linux). Для каждого релиза публикуется файл `SHA256SUMS` с контрольными суммами двух установочных пакетов.

## Номер версии

Репозиторий использует схему CI / Release из проектов Benya9669/Polka и Benya9669/DockerManager. Файл `VERSION` в корне содержит версию в формате `X.Y.Z`. Эта строка задаёт версию приложения, установщиков и релиза. Для выпуска следующей версии измените `VERSION` в том же наборе изменений, что и выпускаемый код.

Workflow запускается для pull request в `main`, push в `main` и по команде Run workflow. Windows и Linux проходят тесты, собирают автономный комплект PyInstaller и проверяют запуск установленного деморежима и консольного помощника. Установщики сохраняются как артефакты запуска. После успешной сборки из `main` workflow проверяет тег `vX.Y.Z`. Для новой версии он публикует GitHub Release с этим тегом на проверенном коммите, автоматически собранным описанием, обоими пакетами и контрольными суммами. Повторная сборка существующей версии сохраняет её опубликованный релиз.

## Локальная сборка

Собирайте каждый пакет на его целевой ОС. Из корня проекта с активированным окружением Python 3.12 выполните

```shell
python -m pip install -r requirements.txt pyinstaller==6.22.3
python -m unittest discover -s tests -v
python -m PyInstaller --noconfirm packaging/desktop.spec
python packaging/smoke.py dist/majorv-desktop
```

В Windows нужен [Inno Setup 6](https://jrsoftware.org/inno-setup/downloads). Вызов из PowerShell для стандартного расположения компилятора

```powershell
$appVersion = (Get-Content VERSION -Raw).Trim()
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" "/DAppVersion=$appVersion" packaging/windows.iss
```

В Ubuntu 24.04 с установленным `dpkg-deb` выполните `bash packaging/debian.sh`. Готовые пакеты обеих ОС находятся в `dist/release/`. Команда `majorv-desktop --demo` в Linux или запуск установленного `majorv-desktop.exe --demo` в Windows открывает деморежим.
