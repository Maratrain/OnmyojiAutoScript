@echo off
rem Build deploy\launcher\oas-launcher.exe with the .NET Framework compiler.
rem The exe is a windowless (winexe) native launcher: hide-start backend, splash, open oasx.
setlocal
cd /d "%~dp0..\.."

set "CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC%" set "CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe"
if not exist "%CSC%" (
    echo csc.exe not found, install .NET Framework 4.x developer pack.
    exit /b 1
)

"%CSC%" /nologo /target:winexe /platform:anycpu /optimize+ ^
    /out:deploy\launcher\oas-launcher.exe ^
    /win32icon:deploy\launcher\logo.ico ^
    /r:System.dll /r:System.Drawing.dll /r:System.Windows.Forms.dll ^
    deploy\launcher\OasLauncher.cs
if errorlevel 1 (
    echo Build failed.
    exit /b 1
)
echo Built deploy\launcher\oas-launcher.exe
endlocal
