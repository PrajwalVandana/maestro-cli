!define PRODUCT_NAME "maestro-cli"

OutFile "maestro-installer.exe"

Section
    ; Set installation directory
    SetOutPath $PROGRAMFILES64\maestro-bundle

    ; Add files to installation directory
    File ..\dist\maestro\maestro.exe
    File /r ..\dist\maestro\_internal

    ; Add $PROGRAMFILES64\maestro-bundle to PATH
    EnVar::SetHKCU
    EnVar::AddValue "Path" "$PROGRAMFILES64\maestro-bundle"

    ; Add uninstaller registry key
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}" "DisplayName" "${PRODUCT_NAME}"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}" "UninstallString" "$PROGRAMFILES64\maestro-uninstall.exe"
SectionEnd

Section -Post
    WriteUninstaller "$PROGRAMFILES64\maestro-uninstall.exe"
SectionEnd

Section "Uninstall"
    ; Remove $PROGRAMFILES64\maestro-bundle
    RMDir /r "$PROGRAMFILES64\maestro-bundle"

    ; Remove $PROGRAMFILES64\maestro-bundle from PATH
    EnVar::SetHKCU
    EnVar::DeleteValue "Path" "$PROGRAMFILES64\maestro-bundle"

    ; Remove uninstaller registry key
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}"

    ; Remove uninstaller
    Delete "$PROGRAMFILES64\maestro-uninstall.exe"
SectionEnd