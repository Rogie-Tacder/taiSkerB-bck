##
## start locally
serverless offline start --reloadHandler

py -m pip install virtualenv
py -m virtualenv .venv
.venv/Scripts/activate.bat

py -m pip install -r requirements.txt
py -m pip freeze > requirements.txt
