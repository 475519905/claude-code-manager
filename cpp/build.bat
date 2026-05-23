@echo off
setlocal
pushd "%~dp0"
if exist "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" (
  call "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
)
set "WINSDKBIN="
for /f "delims=" %%I in ('dir /b /ad "%ProgramFiles(x86)%\Windows Kits\10\bin\10.*" 2^>nul ^| sort /r') do (
  if not defined WINSDKBIN if exist "%ProgramFiles(x86)%\Windows Kits\10\bin\%%I\x64\rc.exe" set "WINSDKBIN=%ProgramFiles(x86)%\Windows Kits\10\bin\%%I\x64"
)
if defined WINSDKBIN set "PATH=%WINSDKBIN%;%PATH%"
set "WEBVIEW2_VERSION=1.0.3967.48"
set "WEBVIEW2_DIR=%CD%\external\webview2"
if not exist "%WEBVIEW2_DIR%\build\native\include\WebView2.h" (
  echo Downloading Microsoft.Web.WebView2 %WEBVIEW2_VERSION% SDK...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $root=(Resolve-Path '.').Path; $version=$env:WEBVIEW2_VERSION; $dst=[IO.Path]::GetFullPath($env:WEBVIEW2_DIR); if(-not $dst.StartsWith($root,[StringComparison]::OrdinalIgnoreCase)){throw 'Unsafe WEBVIEW2_DIR'}; $url='https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/'+$version+'/microsoft.web.webview2.'+$version+'.nupkg'; $tmp=Join-Path $env:TEMP ('microsoft.web.webview2.'+$version+'.'+$PID+'.nupkg'); $zip=Join-Path $env:TEMP ('microsoft.web.webview2.'+$version+'.'+$PID+'.zip'); Invoke-WebRequest -Uri $url -OutFile $tmp; Copy-Item -LiteralPath $tmp -Destination $zip -Force; if(Test-Path -LiteralPath $dst){Remove-Item -LiteralPath $dst -Recurse -Force}; New-Item -ItemType Directory -Force -Path $dst | Out-Null; Expand-Archive -LiteralPath $zip -DestinationPath $dst -Force"
  if errorlevel 1 exit /b %errorlevel%
)
cmake -S . -B build -G "NMake Makefiles" -DCMAKE_BUILD_TYPE=Release -DMANAGER_KIND=codex
if errorlevel 1 exit /b %errorlevel%
cmake --build build
if errorlevel 1 exit /b %errorlevel%
echo.
echo Built: %CD%\build\conv_manager_cpp.exe
set "APP_NAME=CodexManager"
set "SIDECAR_NAME=Codex.exe"
set "PACKAGE_DIR=%CD%\..\dist\cpp\%APP_NAME%"
if not exist "%PACKAGE_DIR%" mkdir "%PACKAGE_DIR%"
copy /Y "build\conv_manager_cpp.exe" "%PACKAGE_DIR%\%APP_NAME%.exe" >nul
if exist "%PACKAGE_DIR%\web" rmdir /S /Q "%PACKAGE_DIR%\web"
xcopy /E /I /Y "%CD%\..\web" "%PACKAGE_DIR%\web" >nul
if exist "%CD%\..\%SIDECAR_NAME%" (
  copy /Y "%CD%\..\%SIDECAR_NAME%" "%PACKAGE_DIR%\%SIDECAR_NAME%" >nul
) else if exist "%CD%\..\..\%SIDECAR_NAME%" (
  copy /Y "%CD%\..\..\%SIDECAR_NAME%" "%PACKAGE_DIR%\%SIDECAR_NAME%" >nul
)
echo Packaged: %PACKAGE_DIR%
popd
