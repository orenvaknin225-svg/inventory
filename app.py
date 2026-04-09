import os
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash
)
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-me-now")

database_url = os.getenv("DATABASE_URL")
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url or "sqlite:///inventory.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


class Part(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    sku = db.Column(db.String(100), unique=True, nullable=False)
    price = db.Column(db.Float, nullable=False, default=0)
    supplier = db.Column(db.String(200), nullable=False)
    stock = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    movements = db.relationship(
        "StockMovement",
        backref="part",
        lazy=True,
        cascade="all, delete-orphan"
    )


class StockMovement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    part_id = db.Column(db.Integer, db.ForeignKey("part.id"), nullable=False)
    movement_type = db.Column(db.String(20), nullable=False)  # add / use
    quantity = db.Column(db.Integer, nullable=False)
    note = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


def is_admin():
    return session.get("role") == "admin"


def is_employee():
    return session.get("role") == "employee"


def is_logged_in():
    return session.get("role") in ["admin", "employee"]


@app.route("/")
def home():
    if is_logged_in():
        return redirect(url_for("parts"))
    return render_template("login.html")


@app.route("/login/admin", methods=["POST"])
def login_admin():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    admin_username = os.getenv("ADMIN_USERNAME", "admin")
    admin_password = os.getenv("ADMIN_PASSWORD", "12345678")

    if username == admin_username and password == admin_password:
        session.clear()
        session["role"] = "admin"
        flash("התחברת כמנהל")
        return redirect(url_for("parts"))

    flash("פרטי מנהל שגויים")
    return redirect(url_for("home"))


@app.route("/login/employee", methods=["POST"])
def login_employee():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    employee_username = os.getenv("EMPLOYEE_USERNAME", "worker")
    employee_password = os.getenv("EMPLOYEE_PASSWORD", "1234")

    if username == employee_username and password == employee_password:
        session.clear()
        session["role"] = "employee"
        flash("התחברת כעובד")
        return redirect(url_for("parts"))

    flash("פרטי עובד שגויים")
    return redirect(url_for("home"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/parts")
def parts():
    if not is_logged_in():
        return redirect(url_for("home"))

    q = request.args.get("q", "").strip()

    query = Part.query
    if q:
        query = query.filter(
            db.or_(
                Part.name.ilike(f"%{q}%"),
                Part.sku.ilike(f"%{q}%")
            )
        )

    parts_list = query.order_by(Part.name.asc()).all()

    return render_template(
        "parts.html",
        parts=parts_list,
        q=q,
        is_admin=is_admin(),
        is_employee=is_employee()
    )


@app.route("/parts/new", methods=["GET", "POST"])
def new_part():
    if not is_admin():
        flash("רק מנהל יכול להוסיף חלק חדש")
        return redirect(url_for("parts"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        sku = request.form.get("sku", "").strip()
        supplier = request.form.get("supplier", "").strip()
        price_raw = request.form.get("price", "").strip()
        stock_raw = request.form.get("stock", "").strip()

        if not name or not sku or not supplier or not price_raw or not stock_raw:
            flash("צריך למלא את כל השדות")
            return redirect(url_for("new_part"))

        exists = Part.query.filter_by(sku=sku).first()
        if exists:
            flash("מק״ט כבר קיים במערכת")
            return redirect(url_for("new_part"))

        try:
            price = float(price_raw)
            stock = int(stock_raw)
        except ValueError:
            flash("מחיר או כמות לא תקינים")
            return redirect(url_for("new_part"))

        if stock < 0 or price < 0:
            flash("מחיר וכמות חייבים להיות 0 או יותר")
            return redirect(url_for("new_part"))

        part = Part(
            name=name,
            sku=sku,
            supplier=supplier,
            price=price,
            stock=stock
        )
        db.session.add(part)
        db.session.commit()

        if stock > 0:
            movement = StockMovement(
                part_id=part.id,
                movement_type="add",
                quantity=stock,
                note="מלאי התחלתי"
            )
            db.session.add(movement)
            db.session.commit()

        flash("החלק נוסף בהצלחה")
        return redirect(url_for("parts"))

    return render_template("new_part.html")


@app.route("/parts/<int:part_id>")
def part_detail(part_id):
    if not is_logged_in():
        return redirect(url_for("home"))

    part = Part.query.get_or_404(part_id)
    movements = StockMovement.query.filter_by(part_id=part.id).order_by(
        StockMovement.created_at.desc()
    ).all()

    return render_template(
        "part_detail.html",
        part=part,
        movements=movements,
        is_admin=is_admin(),
        is_employee=is_employee()
    )


@app.route("/parts/<int:part_id>/add-stock", methods=["POST"])
def add_stock(part_id):
    if not is_admin():
        flash("רק מנהל יכול להוסיף מלאי")
        return redirect(url_for("parts"))

    part = Part.query.get_or_404(part_id)
    quantity_raw = request.form.get("quantity", "").strip()
    note = request.form.get("note", "").strip()

    try:
        quantity = int(quantity_raw)
    except ValueError:
        flash("כמות לא תקינה")
        return redirect(url_for("part_detail", part_id=part.id))

    if quantity <= 0:
        flash("הכמות חייבת להיות גדולה מ-0")
        return redirect(url_for("part_detail", part_id=part.id))

    part.stock += quantity

    movement = StockMovement(
        part_id=part.id,
        movement_type="add",
        quantity=quantity,
        note=note or "הוספת מלאי"
    )
    db.session.add(movement)
    db.session.commit()

    flash("המלאי עודכן בהצלחה")
    return redirect(url_for("part_detail", part_id=part.id))


@app.route("/parts/<int:part_id>/use-stock", methods=["POST"])
def use_stock(part_id):
    if not is_logged_in():
        return redirect(url_for("home"))

    part = Part.query.get_or_404(part_id)
    quantity_raw = request.form.get("quantity", "").strip()
    note = request.form.get("note", "").strip()

    try:
        quantity = int(quantity_raw)
    except ValueError:
        flash("כמות לא תקינה")
        return redirect(url_for("part_detail", part_id=part.id))

    if quantity <= 0:
        flash("הכמות חייבת להיות גדולה מ-0")
        return redirect(url_for("part_detail", part_id=part.id))

    if quantity > part.stock:
        flash("אין מספיק מלאי לחלק הזה")
        return redirect(url_for("part_detail", part_id=part.id))

    part.stock -= quantity

    movement = StockMovement(
        part_id=part.id,
        movement_type="use",
        quantity=quantity,
        note=note or "שימוש בחלק"
    )
    db.session.add(movement)
    db.session.commit()

    flash("השימוש נרשם והמלאי הופחת")
    return redirect(url_for("part_detail", part_id=part.id))


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
