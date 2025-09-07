import os
import uuid
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
import cv2

app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['FACE_FOLDER'] = 'static/faces'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///bildarkiv.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['FLASK_SECRET_KEY'] = 'PetriBildarkiv'

db = SQLAlchemy(app)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['FACE_FOLDER'], exist_ok=True)

# ============== MODELS ==============
# Association table for many-to-many relationship
face_person = db.Table('face_person',
    db.Column('face_id', db.Integer, db.ForeignKey('face.id'), primary_key=True),
    db.Column('person_id', db.Integer, db.ForeignKey('person.id'), primary_key=True)
)

class Image(db.Model):
    id = db.Column(db.String, primary_key=True)
    filename = db.Column(db.String, nullable=False)
    date_taken = db.Column(db.String, nullable=True)
    place_taken = db.Column(db.String, nullable=True)
    description = db.Column(db.Text, nullable=True)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    faces = db.relationship('Face', backref='image', cascade="all, delete-orphan", lazy=True)

class Face(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    image_id = db.Column(db.String, db.ForeignKey('image.id'), nullable=False)
    x = db.Column(db.Integer)
    y = db.Column(db.Integer)
    w = db.Column(db.Integer)
    h = db.Column(db.Integer)
    face_path = db.Column(db.String)
    persons = db.relationship('Person', secondary=face_person, back_populates='faces')

class Person(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String)
    faces = db.relationship('Face', secondary=face_person, back_populates='persons')

# ============== FACE DETECTION ==============
def detect_faces(image_path):
    img = cv2.imread(image_path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    faces = face_cascade.detectMultiScale(gray, 1.1, 4)
    return faces

# ============== ROUTES ==============
@app.route('/', methods=['GET', 'POST'])
def home():
    if request.method == 'POST':
        file = request.files['image']
        if not file:
            return render_template('home.html', msg='No file uploaded')
        filename = secure_filename(file.filename)
        img_id = str(uuid.uuid4())
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{img_id}_{filename}")
        file.save(save_path)
        date_taken = request.form.get('date_taken')
        place_taken = request.form.get('place_taken')
        description = request.form.get('description')

        # Save image metadata to DB
        image = Image(
            id=img_id,
            filename=f"{img_id}_{filename}",
            date_taken=date_taken,
            place_taken=place_taken,
            description=description,
            uploaded_at=datetime.utcnow()
        )
        db.session.add(image)
        db.session.commit()

        # Detect faces and save face crops
        faces = detect_faces(save_path)
        face_objs = []
        for idx, (x, y, w, h) in enumerate(faces):
            img = cv2.imread(save_path)
            face_img = img[y:y+h, x:x+w]
            face_path = os.path.join(app.config['FACE_FOLDER'], f"{img_id}_face{idx}.jpg")
            cv2.imwrite(face_path, face_img)
            face_obj = Face(image_id=img_id, x=int(x), y=int(y), w=int(w), h=int(h), face_path=f"faces/{img_id}_face{idx}.jpg")
            db.session.add(face_obj)
            face_objs.append(face_obj)
        db.session.commit()

        # Prepare faces for template
        face_list = []
        for idx, face in enumerate(face_objs):
            face_list.append({
                'idx': face.id,
                'url': url_for('static', filename=face.face_path),
                'region': (face.x, face.y, face.w, face.h)
            })
        return render_template('faces.html', img_id=img_id, img_url=url_for('uploaded_file', filename=f"{img_id}_{filename}"), faces=face_list)
    return render_template('home.html')

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/identify/<img_id>', methods=['POST'])
def identify(img_id):
    image = Image.query.get_or_404(img_id)
    faces = Face.query.filter_by(image_id=img_id).all()
    # Remove all previous person associations for these faces
    for face in faces:
        face.persons.clear()
    db.session.commit()
    # Add submitted names (allowing multiple persons per face)
    for face in faces:
        names_str = request.form.get(f"person_name_{face.id}")
        if names_str:
            # Support multiple names separated by commas
            for name in [n.strip() for n in names_str.split(",") if n.strip()]:
                person = Person.query.filter_by(name=name).first()
                if not person:
                    person = Person(name=name)
                    db.session.add(person)
                    db.session.commit()
                if person not in face.persons:
                    face.persons.append(person)
    db.session.commit()
    return redirect(url_for('result', img_id=img_id))

@app.route('/result/<img_id>')
def result(img_id):
    highlight_person_id = request.args.get('highlight_person_id', type=int)
    image = Image.query.get_or_404(img_id)
    faces = Face.query.filter_by(image_id=img_id).all()
    face_data = []
    persons_display = {}
    highlights = set()
    for face in faces:
        face_data.append({
            'idx': face.id,
            'region': (face.x, face.y, face.w, face.h)
        })
        person_names = [p.name for p in face.persons]
        persons_display[face.id] = ", ".join(person_names)
        if highlight_person_id and any(p.id == highlight_person_id for p in face.persons):
            highlights.add(face.id)
    return render_template('result.html', metadata={
        'filename': image.filename,
        'date_taken': image.date_taken,
        'place_taken': image.place_taken,
        'description': image.description,
        'uploaded_at': image.uploaded_at,
        'faces': face_data,
        'persons': persons_display,
        'img_id': image.id,
        'highlights': list(highlights)
    })

@app.route('/gallery')
def gallery():
    images = Image.query.order_by(Image.uploaded_at.desc()).all()
    img_data = []
    for image in images:
        face_objs = Face.query.filter_by(image_id=image.id).all()
        person_names = set()
        for f in face_objs:
            for p in f.persons:
                person_names.add(p.name)
        img_data.append({
            'id': image.id,
            'filename': image.filename,
            'date_taken': image.date_taken,
            'place_taken': image.place_taken,
            'description': image.description,
            'uploaded_at': image.uploaded_at,
            'thumb_url': url_for('uploaded_file', filename=image.filename),
            'faces_count': len(face_objs),
            'persons': sorted(person_names)
        })
    return render_template('gallery.html', images=img_data)

@app.route('/search', methods=['GET', 'POST'])
def search():
    results = []
    search_name = ""
    search_date = ""
    search_place = ""
    highlight_person_id = None
    if request.method == 'POST':
        search_name = request.form.get('person_name', '').strip()
        search_date = request.form.get('date_taken', '').strip()
        search_place = request.form.get('place_taken', '').strip()
        # Find matching persons (if any)
        person_ids = []
        if search_name:
            persons = Person.query.filter(Person.name.ilike(f"%{search_name}%")).all()
            person_ids = [p.id for p in persons]
        # Find faces for those persons
        found_image_ids = set()
        if person_ids:
            faces = Face.query.join(Face.persons).filter(Person.id.in_(person_ids)).all()
            for face in faces:
                found_image_ids.add(face.image_id)
            # For demo: if only one person was found, highlight their faces
            if len(person_ids) == 1:
                highlight_person_id = person_ids[0]
        else:
            # If not searching by person, consider all images
            found_image_ids = set(i.id for i in Image.query.all())
        # Filter images by date and place
        q = Image.query.filter(Image.id.in_(found_image_ids))
        if search_date:
            q = q.filter(Image.date_taken == search_date)
        if search_place:
            q = q.filter(Image.place_taken.ilike(f"%{search_place}%"))
        images = q.order_by(Image.uploaded_at.desc()).all()
        # Prepare results
        for image in images:
            face_objs = Face.query.filter_by(image_id=image.id).all()
            person_names = set()
            for f in face_objs:
                for p in f.persons:
                    person_names.add(p.name)
            results.append({
                'id': image.id,
                'filename': image.filename,
                'date_taken': image.date_taken,
                'place_taken': image.place_taken,
                'description': image.description,
                'uploaded_at': image.uploaded_at,
                'thumb_url': url_for('uploaded_file', filename=image.filename),
                'faces_count': len(face_objs),
                'persons': sorted(person_names)
            })
    return render_template('search.html',
                           images=results,
                           search_name=search_name,
                           search_date=search_date,
                           search_place=search_place,
                           highlight_person_id=highlight_person_id)

# ============== DB RESET ==============
@app.route('/reset-db')
def reset_db():
    db_path = app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
    try:
        if os.path.exists(db_path):
            os.remove(db_path)
        db.create_all()
        for folder in [app.config['UPLOAD_FOLDER'], app.config['FACE_FOLDER']]:
            for f in os.listdir(folder):
                try:
                    os.remove(os.path.join(folder, f))
                except Exception:
                    pass
        flash("Database and images reset successfully!", "success")
    except Exception as e:
        flash(f"Error during reset: {e}", "danger")
    return redirect(url_for('gallery'))

@app.before_first_request
def create_tables():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5005)