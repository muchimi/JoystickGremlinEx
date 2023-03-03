@echo "Starting to build Gremlin ..."
cd /d %0\..

@echo "Building executable ..."
python -m PyInstaller -y --clean joystick_gremlin.spec
cd dist
if exist joystick_gremlin.zip del joystick_gremlin.zip
cd joystick_gremlin

"C:\Program Files\7-Zip\7z" a -r ../joystick_gremlin.zip *
cd ..\..