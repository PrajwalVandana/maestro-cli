OutFile "maestro-installer.exe"
SetOutPath "$PROGRAMFILES\maestro-bundle"

Section
    ; Add ../dist/maestro and ../dist/_internal to $PROGRAMFILES/maestro-bundle
    File ../dist/maestro
    File /r ../dist/_internal

    ; Add $PROGRAMFILES/maestro-bundle to PATH
    EnVar::AddValue HKCU "Path" "$PROGRAMFILES\maestro-bundle"
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
SectionEnd