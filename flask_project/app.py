import json
import copy
import random
from flask import Flask, render_template, request, redirect, url_for, send_file, jsonify, session, flash
from functools import wraps
import pandas as pd
import os
import io
from werkzeug.utils import secure_filename

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
DATA_FILE = os.path.join("..", "timetable_data.json")
SECTIONS_FILE = "sections_config.json"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.secret_key = "super_secret_mini_project_key_for_timetable" # Ensure sessions work
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "123"

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.url))
        return f(*args, **kwargs)
    return decorated_function

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def load_lab_resources():
    paths = ["lab_resources.json", os.path.join("..", "lab_resources.json")]
    for path in paths:
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    return {"department_rooms": {}, "shared_blocks": {}}

def load_sections():
    if os.path.exists(SECTIONS_FILE):
        with open(SECTIONS_FILE, "r") as f:
            return json.load(f)
    # Default: 1 section per dept per sem (e.g., CS1)
    return {}

def save_sections(data):
    with open(SECTIONS_FILE, "w") as f:
        json.dump(data, f, indent=4)

def get_sections_for(dept, sem):
    """Get sections list for a dept+sem. Falls back to ['Section 1']."""
    sections = load_sections()
    key = f"{dept}|{sem}"
    return sections.get(key, [f"{dept}1"])

# ──────────────────────────────────────────────
# Global storage for all generated timetables
# NEW FORMAT: { "IT": { "First Year": { "IT1": { "Monday": [...], ... }, "IT2": {...} } } }
# ──────────────────────────────────────────────
all_timetables = load_data()

# ══════════════════════════════════════════════
# HELPER: Iterate all timetables (dept → sem → section → schedule)
# ══════════════════════════════════════════════
def iter_all_timetables(all_tt):
    """Yields (dept, sem, section, schedule) for every timetable."""
    for dept, sems in all_tt.items():
        for sem, sections in sems.items():
            for section, schedule in sections.items():
                yield dept, sem, section, schedule

def is_teacher_free(teacher_name, day, period_idx, all_tt, skip_dept, skip_sem, skip_section):
    """Check teacher availability across ALL sections globally, skipping the current one."""
    for dept, sem, section, schedule in iter_all_timetables(all_tt):
        if dept == skip_dept and sem == skip_sem and section == skip_section:
            continue
        slot = schedule[day][period_idx]
        if isinstance(slot, dict) and slot.get("teacher") == teacher_name:
            return False
    return True

def is_room_free(room_name, day, period_start, all_tt, skip_dept, skip_sem, skip_section):
    """Check room availability across ALL sections globally."""
    if not room_name:
        return True
    num_periods = 6
    for dept, sem, section, schedule in iter_all_timetables(all_tt):
        if dept == skip_dept and sem == skip_sem and section == skip_section:
            continue
        for p in range(period_start, period_start + 3):
            if p >= num_periods:
                continue # Skip out of bounds periods instead of returning False
            slot = schedule[day][p]
            if isinstance(slot, dict) and slot.get("room") == room_name:
                return False
    return True

def make_empty_timetable():
    """Create a blank weekly timetable."""
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    return {
        day: [{"subject": "Free", "teacher": "Free", "type": "Free", "room": ""} for _ in range(6)]
        for day in days
    }

def ensure_timetable(all_tt, dept, sem, section):
    """Ensure a dept/sem/section timetable exists."""
    if dept not in all_tt:
        all_tt[dept] = {}
    if sem not in all_tt[dept]:
        all_tt[dept][sem] = {}
    if section not in all_tt[dept][sem]:
        all_tt[dept][sem][section] = make_empty_timetable()

# ══════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════

@app.route("/")
def home():
    return render_template("home.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form["username"] == ADMIN_USERNAME and request.form["password"] == ADMIN_PASSWORD:
            session["logged_in"] = True
            flash("Successfully logged in!", "success")
            next_url = request.args.get("next")
            return redirect(next_url or url_for("home"))
        else:
            flash("Invalid credentials. Please try again.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    flash("You have been logged out.", "info")
    return redirect(url_for("home"))

@app.route("/create")
@login_required
def create_page():
    return render_template("create.html")

@app.route("/lab")
@login_required
def lab_page():
    resources = load_lab_resources()
    return render_template("lab.html", resources=resources)

@app.route("/view")
def view_page():
    teachers = set()
    for dept, sem, section, schedule in iter_all_timetables(all_timetables):
        for day_slots in schedule.values():
            for slot in day_slots:
                if isinstance(slot, dict) and slot.get("teacher") and slot["teacher"] != "Free":
                    teachers.add(slot["teacher"])

    return render_template("view.html",
                           timetables=all_timetables,
                           teachers=sorted(list(teachers)),
                           departments=sorted(list(all_timetables.keys())))

@app.route("/get_lab_metadata")
def get_lab_metadata():
    resources = load_lab_resources()
    departments = ["Applied Science", "CS", "IT", "MECH", "EE", "EC", "CIVIL"]
    for d in all_timetables.keys():
        if d not in departments:
            departments.append(d)

    return {
        "departments": departments,
        "branch_depts": ["CS", "IT", "MECH", "EE", "EC", "CIVIL"],
        "rooms": resources,
        "years": ["First Year", "Second Year", "Third Year", "Fourth Year"],
        "sections_config": load_sections()
    }

@app.route("/save_sections", methods=["POST"])
@login_required
def save_sections_route():
    data = request.json
    save_sections(data)
    return jsonify({"status": "success"})

# ══════════════════════════════════════════════
# BULK LAB GENERATION (with sections + linked depts)
# ══════════════════════════════════════════════
@app.route("/generate_bulk_labs", methods=["POST"])
@login_required
def generate_bulk_labs():
    global all_timetables
    payload = request.json
    entries = payload.get("entries", [])

    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    num_periods = 6
    start_positions = [0, 1, 2, 3]

    failed_placements = []
    success_count = 0

    for entry in entries:
        dept = entry.get("dept")
        sem = entry.get("sem")
        section = entry.get("section", f"{dept}1")
        avoid_day = entry.get("avoid")
        linked_depts = entry.get("linked_depts", [])  # Changed from linked_entries

        if not dept or not sem:
            continue

        ensure_timetable(all_timetables, dept, sem, section)
        timetable = all_timetables[dept][sem][section]
        labs = [entry.get("lab1"), entry.get("lab2")]

        placed_days = []

        for lab in labs:
            if not lab or not lab.get("subject") or not lab.get("room"):
                continue

            lab_code = lab["subject"]
            room = lab["room"]
            teacher = lab.get("teacher", "TBA")

            placed = False

            search_days = list(days)
            random.shuffle(search_days)
            search_positions = list(start_positions)
            random.shuffle(search_positions)

            for day in search_days:
                if placed:
                    break
                if day == avoid_day or day in placed_days:
                    continue

                for start_p in search_positions:
                    # Check own slots
                    slots_free = all(timetable[day][p]["subject"] == "Free" for p in range(start_p, start_p + 3))
                    # Check global room
                    room_free = is_room_free(room, day, start_p, all_timetables, dept, sem, section)
                    # Check global teacher
                    teacher_free = all(
                        is_teacher_free(teacher, day, p, all_timetables, dept, sem, section)
                        for p in range(start_p, start_p + 3)
                    ) if teacher != "TBA" else True

                    # Check linked sections are free
                    linked_free = True
                    for ld in linked_depts:
                        ls = f"{ld}1" # Default to Section 1 for linked branches
                        ensure_timetable(all_timetables, ld, sem, ls)
                        linked_tt = all_timetables[ld][sem][ls]
                        if not all(linked_tt[day][p]["subject"] == "Free" for p in range(start_p, start_p + 3)):
                            linked_free = False
                            break

                    if slots_free and room_free and teacher_free and linked_free:
                        slot_data = {"subject": lab_code, "teacher": teacher, "type": "Lab", "room": room}
                        for p in range(start_p, start_p + 3):
                            timetable[day][p] = slot_data.copy()
                        placed = True
                        placed_days.append(day)
                        success_count += 1

                        # Mirror to linked sections
                        if linked_depts:
                            mirror = {
                                "subject": lab_code, "teacher": teacher,
                                "type": "Lab", "room": room,
                                "linked": True, "linked_from": dept
                            }
                            for ld in linked_depts:
                                ls = f"{ld}1"
                                for p in range(start_p, start_p + 3):
                                    all_timetables[ld][sem][ls][day][p] = mirror.copy()
                        break

            if not placed:
                failed_placements.append(f"{lab_code} ({teacher}) for {dept} {sem} {section}")

    save_data(all_timetables)

    if failed_placements:
        return jsonify({
            "status": "partial",
            "message": f"{success_count} labs placed. {len(failed_placements)} could not be placed.",
            "failed": failed_placements
        })

    return jsonify({"status": "success", "message": f"All {success_count} labs allocated successfully!"})

@app.route("/save_lab_resources", methods=["POST"])
@login_required
def save_lab_resources():
    data = request.json
    with open("lab_resources.json", "w") as f:
        json.dump(data, f, indent=4)
    return {"status": "success"}

@app.route("/clear_data", methods=["POST"])
@login_required
def clear_data():
    global all_timetables
    payload = request.json
    scope = payload.get("scope", "all")
    dept = payload.get("dept")
    sem = payload.get("sem")
    section = payload.get("section")

    if scope == "all":
        all_timetables = {}
        save_data(all_timetables)
        return jsonify({"status": "success", "message": "All timetable data cleared."})
    elif scope == "dept" and dept:
        if dept in all_timetables:
            if sem and sem in all_timetables[dept]:
                if section and section in all_timetables[dept].get(sem, {}):
                    del all_timetables[dept][sem][section]
                    if not all_timetables[dept][sem]:
                        del all_timetables[dept][sem]
                    if not all_timetables[dept]:
                        del all_timetables[dept]
                    save_data(all_timetables)
                    return jsonify({"status": "success", "message": f"Cleared {dept} - {sem} - {section}."})
                else:
                    del all_timetables[dept][sem]
                    if not all_timetables[dept]:
                        del all_timetables[dept]
                    save_data(all_timetables)
                    return jsonify({"status": "success", "message": f"Cleared {dept} - {sem}."})
            else:
                del all_timetables[dept]
                save_data(all_timetables)
                return jsonify({"status": "success", "message": f"Cleared entire {dept} department."})
    return jsonify({"status": "error", "message": "Nothing to clear."})

# ══════════════════════════════════════════════
# EXCEL UPLOAD (Theory + Lab from files)
# ══════════════════════════════════════════════
@app.route("/generate", methods=["POST"])
@login_required
def generate():
    global all_timetables

    dept_choice = request.form.get("dept_dropdown", "General").strip()
    dept_custom = request.form.get("dept_custom", "").strip()
    department_name = dept_custom if dept_choice == "Other" else dept_choice

    year_name = request.form.get("year_name", "Unnamed Year").strip()
    section_name = request.form.get("section_name", f"{department_name}1").strip()
    teacher_file = request.files.get("teacher_file")
    lab_file = request.files.get("lab_file")

    if teacher_file and lab_file:
        t_filename = secure_filename(teacher_file.filename)
        l_filename = secure_filename(lab_file.filename)
        teacher_path = os.path.join(app.config["UPLOAD_FOLDER"], f"teacher_{department_name}_{year_name}_{section_name}_{t_filename}")
        lab_path = os.path.join(app.config["UPLOAD_FOLDER"], f"lab_{department_name}_{year_name}_{section_name}_{l_filename}")

        teacher_file.save(teacher_path)
        lab_file.save(lab_path)

        try:
            teacher_df = pd.read_excel(teacher_path)
            lab_df = pd.read_excel(lab_path)

            teacher_data = teacher_df.to_dict(orient="records")
            lab_data = lab_df.to_dict(orient="records")

            new_timetable = generate_timetable(teacher_data, lab_data, all_timetables, department_name, year_name, section_name)

            ensure_timetable(all_timetables, department_name, year_name, section_name)
            all_timetables[department_name][year_name][section_name] = new_timetable
            save_data(all_timetables)

            return redirect(url_for("view_page"))
        except Exception as e:
            return f"Error processing files: {str(e)}"

    return "File upload failed. Please ensure both Teacher and Lab files are selected."

# ══════════════════════════════════════════════
# DOWNLOAD
# ══════════════════════════════════════════════
@app.route("/download/<type>/<path:value>")
def download(type, value):
    output = io.BytesIO()
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    periods = ["P1", "P2", "P3", "P4", "P5", "P6"]

    data = []

    if type == "class":
        try:
            parts = value.split("/")
            dept, sem, section = parts[0], parts[1], parts[2]
            sec_data = all_timetables[dept][sem][section]
            for day in days:
                row = {"Day": day}
                for i, p in enumerate(periods):
                    slot = sec_data[day][i]
                    if isinstance(slot, dict) and slot.get("subject") != "Free":
                        row[p] = f"{slot['subject']} ({slot['teacher']})"
                    else:
                        row[p] = "Free"
                data.append(row)
        except:
            return "Invalid class selection."

    elif type == "teacher":
        for day in days:
            row = {"Day": day}
            for i, p in enumerate(periods):
                found = False
                for dept, sem, section, schedule in iter_all_timetables(all_timetables):
                    slot = schedule[day][i]
                    if isinstance(slot, dict) and slot.get("teacher") == value:
                        row[p] = f"{slot['subject']} ({dept} - {sem} - {section})"
                        found = True
                        break
                if not found:
                    row[p] = "Free"
            data.append(row)

    if not data:
        return "No data found for the requested timetable."

    df = pd.DataFrame(data)
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Timetable')

    output.seek(0)
    filename = value.replace("/", "_")
    return send_file(output, as_attachment=True, download_name=f"Timetable_{filename}.xlsx")

# ══════════════════════════════════════════════
# COLUMN HELPER
# ══════════════════════════════════════════════
def get_col(row, *possible_names):
    """Helper to find column values ignoring case and spaces"""
    for col in row.keys():
        cleaned_col = str(col).lower().replace(" ", "").replace("/", "").replace("_", "")
        for poss in possible_names:
            cleaned_poss = poss.lower().replace(" ", "").replace("/", "").replace("_", "")
            if cleaned_col == cleaned_poss:
                return row[col]
    return None

# ══════════════════════════════════════════════
# 🧠 TIMETABLE GENERATION ENGINE
# ══════════════════════════════════════════════
def generate_timetable(teachers, labs, existing_timetables, current_dept, current_sem, current_section):
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    num_periods = 6

    # Load existing timetable or create fresh
    timetable = None
    if current_dept in existing_timetables:
        if current_sem in existing_timetables[current_dept]:
            if current_section in existing_timetables[current_dept][current_sem]:
                timetable = copy.deepcopy(existing_timetables[current_dept][current_sem][current_section])

    if not timetable:
        timetable = make_empty_timetable()

    # 🔹 Step 1: Place Labs as FIXED 3-continuous-period blocks (with validation)
    for lab in labs:
        try:
            day = get_col(lab, "day")
            if not day or str(day).title() not in days:
                continue
            day = str(day).title()

            start_val = get_col(lab, "startperiod", "start")
            end_val = get_col(lab, "endperiod", "end")

            start = int(start_val) - 1 if start_val else 0
            end = int(end_val) if end_val else start + 3

            teacher = get_col(lab, "teachername", "teacher") or "TBA"
            subject = get_col(lab, "labsubject", "subject") or "Lab"
            room = get_col(lab, "room", "labroom") or ""

            end = min(start + 3, num_periods)

            can_place = True
            if teacher != "TBA":
                for i in range(start, end):
                    if not is_teacher_free(teacher, day, i, existing_timetables, current_dept, current_sem, current_section):
                        print(f"⚠️ Excel Lab clash: Teacher '{teacher}' busy on {day} P{i+1}")
                        can_place = False
                        break
            if can_place and room:
                if not is_room_free(room, day, start, existing_timetables, current_dept, current_sem, current_section):
                    print(f"⚠️ Excel Lab clash: Room '{room}' busy on {day} P{start+1}")
                    can_place = False

            if can_place:
                for i in range(start, end):
                    timetable[day][i] = {"subject": subject, "teacher": teacher, "type": "Lab", "room": room}
            else:
                print(f"⚠️ Skipped Excel lab '{subject}' on {day} due to clashes.")
        except Exception as e:
            print("Lab placement error:", e)
            continue

    # 🔹 Step 2: Place Theory subjects
    def get_free_slots():
        slots = []
        for day in days:
            for i in range(num_periods):
                if timetable[day][i]["subject"] == "Free":
                    slots.append((day, i))
        random.shuffle(slots)
        return slots

    def is_adjacent_same_teacher(teacher, day, period_idx):
        for adj in [period_idx - 1, period_idx + 1]:
            if 0 <= adj < num_periods:
                slot = timetable[day][adj]
                if isinstance(slot, dict) and slot.get("teacher") == teacher and slot.get("type") == "Theory":
                    return True
        return False

    shuffled_teachers = list(teachers)
    random.shuffle(shuffled_teachers)

    for subject_info in shuffled_teachers:
        type_val = str(get_col(subject_info, "type(theorylab)", "type") or "theory").strip().lower()

        if type_val == "theory":
            hours_val = get_col(subject_info, "hoursperweek", "hours")
            hours = int(hours_val) if pd.notna(hours_val) else 0

            name = get_col(subject_info, "subjectname", "subject") or "Subject"
            teacher = get_col(subject_info, "teachername", "teacher") or "TBA"

            # Pass 1: Strict (no adjacent same teacher)
            free_slots = get_free_slots()
            for (day, i) in free_slots:
                if hours <= 0:
                    break
                if timetable[day][i]["subject"] != "Free":
                    continue
                if is_teacher_free(teacher, day, i, existing_timetables, current_dept, current_sem, current_section):
                    if not is_adjacent_same_teacher(teacher, day, i):
                        timetable[day][i] = {"subject": name, "teacher": teacher, "type": "Theory"}
                        hours -= 1

            # Pass 2: Relaxed
            if hours > 0:
                free_slots = get_free_slots()
                for (day, i) in free_slots:
                    if hours <= 0:
                        break
                    if timetable[day][i]["subject"] != "Free":
                        continue
                    if is_teacher_free(teacher, day, i, existing_timetables, current_dept, current_sem, current_section):
                        timetable[day][i] = {"subject": name, "teacher": teacher, "type": "Theory"}
                        hours -= 1

    return timetable

if __name__ == "__main__":
    app.run(debug=True)
