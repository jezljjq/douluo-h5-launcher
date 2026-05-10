@echo off
cd /d "%~dp0"
py -3.14-32 -c "from douluo_launcher.dm_client import diagnose_dm_environment; print('\n'.join(diagnose_dm_environment('dm.dmsoft')))"
