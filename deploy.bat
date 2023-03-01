@echo "Starting to build Gremlin ..."
cd /d %0\..

@echo "Building executable ..."
python -m PyInstaller -y --clean joystick_gremlin.spec
