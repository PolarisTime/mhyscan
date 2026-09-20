@echo off
chcp 65001 >nul
setlocal
set "MHYSCAN_CONFIG=%~dp0Config\userinfo.json"
"%~dp0mhyscan.exe" %*
if "%~1"=="" (
  echo.
  echo [提示] 以上是帮助信息。这是命令行工具，请在终端里带参数运行，例如:
  echo    mhyscan.bat scan 6
  echo    mhyscan.bat login
  echo    mhyscan.bat accounts
  pause
)
endlocal
