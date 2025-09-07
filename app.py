#
# Flask application
# https://flask.palletsprojects.com/en/1.1.x/
#
import os
from flask import Flask, render_template, request
from werkzeug.utils import secure_filename

app = Flask(__name__, template_folder='templates')
#app.config['EXPLAIN_TEMPLATE_LOADING'] = True
app.config['FLASK_SECRET_KEY'] = 'PetriBildarkiv'
@app.route('/')
def home(msg=''):
    pass

if __name__ == '__main__':
   app.run(debug=True, host='0.0.0.0', port = 5005)  #enable debug support. The server will then reload itself if the code changes

