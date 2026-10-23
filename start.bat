@echo off
chcp 65001 >nul
pushd "%~dp0"
if exist "LiteReAct.exe" goto portable
where py >nul 2>nul
if errorlevel 1 goto python
py -3 run.py %*
goto done
:python
python run.py %*
goto done
:portable
"%~dp0LiteReAct.exe" %*
:done
popd
pause
