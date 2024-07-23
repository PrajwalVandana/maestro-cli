!define PRODUCT_NAME "maestro-cli"

OutFile "maestro-installer.exe"

Section
    ; Add ../dist/maestro and ../dist/_internal to $PROGRAMFILES/maestro-bundle
    File ../dist/maestro/maestro
    File /r ../dist/maestro/_internal

    ; Add $PROGRAMFILES/maestro-bundle to PATH
    EnVar::AddValue HKCU "Path" "$PROGRAMFILES\maestro-bundle"

    ; Add uninstaller registry key
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}" "DisplayName" "${PRODUCT_NAME}"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}" "UninstallString" "$PROGRAMFILES\maestro-uninstall.exe"
SectionEnd

Section -Post
    ; Write uninstaller
    WriteUninstaller "$PROGRAMFILES\maestro-uninstall.exe"
SectionEnd

; Uninstaller
Section "Uninstall"
    ; Remove $PROGRAMFILES/maestro-bundle
    RMDir /r "$PROGRAMFILES\maestro-bundle"

    ; Remove $PROGRAMFILES/maestro from PATH
    EnVar::RemoveValue HKCU "Path" "$PROGRAMFILES\maestro-bundle"

    ; Remove $PROGRAMFILES/maestro-uninstall.exe
    Delete "$PROGRAMFILES\maestro-uninstall.exe"

    ; Remove uninstaller registry key
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}"
SectionEnd