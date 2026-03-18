@echo off
echo Optimizing Lambda Layer...

cd layer\python

echo Removing test files...
for /d /r %%d in (*test*) do @if exist "%%d" rd /s /q "%%d"
for /d /r %%d in (*tests*) do @if exist "%%d" rd /s /q "%%d"

echo Removing documentation...
for /d /r %%d in (*doc*) do @if exist "%%d" rd /s /q "%%d"
for /d /r %%d in (*docs*) do @if exist "%%d" rd /s /q "%%d"

echo Removing examples...
for /d /r %%d in (*example*) do @if exist "%%d" rd /s /q "%%d"

echo Removing .pyc and __pycache__...
del /s /q *.pyc 2>nul
for /d /r %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d"

echo Removing .dist-info...
for /d /r %%d in (*.dist-info) do @if exist "%%d" rd /s /q "%%d"

echo Done!
cd ..\..
