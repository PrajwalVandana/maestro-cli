; !include "EnVar.nsh"

!define PRODUCT_NAME "maestro-cli"

OutFile "maestro-installer.exe"

Section
    ; Set output path to the installation directory.
    SetOutPath $PROGRAMFILES64\maestro-bundle

    File ..\dist\maestro\maestro.exe
    File /r ..\dist\maestro\_internal

    ; Add $PROGRAMFILES64\maestro-bundle to PATH
    EnVar::AddValue HKCU "Path" "$PROGRAMFILES64\maestro-bundle"

    ; Add uninstaller registry key
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}" "DisplayName" "${PRODUCT_NAME}"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}" "UninstallString" "$PROGRAMFILES64\maestro-uninstall.exe"
SectionEnd

Section -Post
    ; Write uninstaller
    WriteUninstaller "$PROGRAMFILES64\maestro-uninstall.exe"
SectionEnd

; Uninstaller
Section "Uninstall"
    ; Remove $PROGRAMFILES64\maestro-bundle
    RMDir /r "$PROGRAMFILES64\maestro-bundle"

    ; Remove $PROGRAMFILES64\maestro from PATH
    EnVar::DeleteValue HKCU "Path" "$PROGRAMFILES64\maestro-bundle"

    ; Remove $PROGRAMFILES64\maestro-uninstall.exe
    Delete "$PROGRAMFILES64\maestro-uninstall.exe"

    ; Remove uninstaller registry key
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}"
SectionEnd