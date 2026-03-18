@echo off
echo Building VozLab Lambda packages...

cd ..

REM Create build directory
if exist .aws-sam\build rmdir /s /q .aws-sam\build
mkdir .aws-sam\build\ApiFunction
mkdir .aws-sam\build\AnalyzerFunction

REM Install dependencies
echo Installing dependencies...
py -m pip install -r requirements.txt -t .aws-sam\build\ApiFunction --upgrade
py -m pip install -r requirements.txt -t .aws-sam\build\AnalyzerFunction --upgrade

REM Copy application code
echo Copying application code...
xcopy /E /I /Y app .aws-sam\build\ApiFunction\app
xcopy /E /I /Y app .aws-sam\build\AnalyzerFunction\app
copy /Y analysis_handler.py .aws-sam\build\AnalyzerFunction\

echo Build complete!
echo.
echo Next step: Deploy manually or install Python 3.12 for SAM
