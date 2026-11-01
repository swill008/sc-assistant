@echo off
rem Remove the desktop / Start menu / startup shortcuts.
rem The app folder, the C:\scov environment and your settings are kept.
setlocal
cd /d "%~dp0"

echo Removing SC Assistant shortcuts (and old Citizen Assistant ones) ...
rem ONE-TIME (rename to SC Assistant): -Remove also drops the old "Citizen
rem Assistant" shortcuts of a source copy; an installed copy's are left alone.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\make_shortcuts.ps1" -Remove
echo.
echo Shortcuts removed.
echo The app folder, C:\scov and %%APPDATA%%\SC Assistant were left untouched.
echo Delete the app folder to remove the overlay completely.
echo.
pause
endlocal

