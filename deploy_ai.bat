@echo "Starting to build GremlinEx..."
cd /d %0\..
cd dist
if exist gremlinEx\ (
 rmdir gremlinEx\ /q /s
) 
md gremlinEx

cd ..

@echo "Building AI mode executable ..."
c:\python\python313\python -m PyInstaller -y --log-level INFO --clean gremlinExAI.spec
cd dist



if exist joystick_gremlin.zip del joystick_gremlin.zip
if exist gremlinExAI.zip del gremlinExAI.zip
cd gremlinEx


"C:\Program Files\7-Zip\7z" a -r ../gremlinExAI.zip *
cd ..\..
pause