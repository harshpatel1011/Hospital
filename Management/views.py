from django.shortcuts import render, redirect
from django.contrib import messages
from .models import Doctor, Patient, Staff, Appointment, MedicalRecord, Medisense
import re
from django.contrib.auth.hashers import make_password, check_password


def get_current_doctor(request):
    doctor_id = request.session.get("doctor_id")
    if doctor_id:
        return Doctor.objects.filter(id=doctor_id).first()
    return None


def get_current_admin(request):
    admin_id = request.session.get("admin_id")
    if admin_id == 1 or admin_id == "1":
        return {"id": 1, "username": "Harsh", "role": "Admin"}
    return None


# --- PUBLIC VIEWS ---


def home(request):
    user = get_current_doctor(request)
    return render(request, "index.html", {"user": user})


def book_appointment(request):
    if request.method == "POST":
        patient_name = request.POST.get("patient_name")
        age = request.POST.get("age")
        gender = request.POST.get("gender")
        address = request.POST.get("address")
        phone = request.POST.get("phone")
        date = request.POST.get("date")
        time = request.POST.get("time")
        doctor_id = request.POST.get("doctor")
        reason = request.POST.get("reason")

        doctor = None
        if doctor_id:
            doctor = Doctor.objects.filter(id=doctor_id, role="Doctor").first()

        Appointment.objects.create(
            patient_name=patient_name,
            age=age,
            gender=gender,
            address=address,
            phone=phone,
            date=date,
            time=time,
            doctor=doctor,
            reason=reason,
        )
        messages.success(
            request, "Appointment booked successfully! We will contact you soon."
        )
        return redirect("home")

    doctors = Doctor.objects.filter(role="Doctor", is_approved=True)
    return render(request, "book_appointment.html", {"doctors": doctors})


# --- AUTH VIEWS ---


def doctor_signup(request):
    if get_current_doctor(request):
        return redirect("home")

    if request.method == "POST":
        username = request.POST.get("username")
        email = request.POST.get("email")
        password = request.POST.get("password")
        password_confirm = request.POST.get("password_confirm")
        specialization = request.POST.get("specialization", "")
        phone = request.POST.get("phone", "")

        if not re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$", email):
            messages.error(request, "Invalid email format!")
            return redirect("signup")

        if phone and not re.match(r"^\+?[0-9]{10,15}$", phone):
            messages.error(
                request,
                "Invalid phone number format. It should contain 10 to 15 digits.",
            )
            return redirect("signup")

        if not re.match(
            r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*#?&]).{8,}$", password
        ):
            messages.error(
                request,
                "Password must be at least 8 characters long, contain at least one uppercase letter, one lowercase letter, one number, and one special character.",
            )
            return redirect("signup")

        if password != password_confirm:
            messages.error(request, "Passwords do not match!")
            return redirect("signup")

        if Doctor.objects.filter(username=username).exists():
            messages.error(request, "Username already taken!")
            return redirect("signup")

        if Doctor.objects.filter(email=email).exists():
            messages.error(request, "Email already registered!")
            return redirect("signup")

        Doctor.objects.create(
            username=username,
            email=email,
            password=make_password(password),
            role="Doctor",
            specialization=specialization,
            phone=phone,
        )
        messages.success(request, "Account created! Please wait for Admin approval.")

        return redirect("login")

    return render(request, "doctor/signup.html")


def doctor_login(request):
    if get_current_doctor(request):
        return redirect("home")

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = Doctor.objects.filter(username=username, role="Doctor").first()

        if user:
            if check_password(password, user.password):
                if not user.is_approved:
                    messages.error(request, "Your account is pending admin approval.")
                    return redirect("login")

                request.session["doctor_id"] = user.id
                messages.success(request, f"Welcome back, Dr. {user.username}!")
                return redirect("doctor_dashboard")
            else:
                messages.error(request, "Invalid password!")
        else:
            messages.error(request, "Invalid username or you are not a Doctor!")
            return redirect("login")

    return render(request, "doctor/login.html")


def admin_login(request):
    if get_current_admin(request):
        return redirect("admin_dashboard")

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        if username == "Harsh" and password == "Patel@123":
            request.session["admin_id"] = 1
            messages.success(request, f"Welcome back Admin {username}!")
            return redirect("admin_dashboard")
        else:
            messages.error(request, "Invalid admin credentials!")

    return render(request, "admin/login.html")


def doctor_logout(request):
    if "doctor_id" in request.session:
        del request.session["doctor_id"]
    messages.success(request, "Successfully logged out!")
    return redirect("home")


def admin_logout(request):
    if "admin_id" in request.session:
        del request.session["admin_id"]
    messages.success(request, "Admin successfully logged out!")
    return redirect("admin_login")


# --- DOCTOR VIEWS ---


def doctor_dashboard(request):
    user = get_current_doctor(request)
    if not user or user.role != "Doctor":
        return redirect("login")

    appointments = Appointment.objects.filter(doctor=user).order_by("-date")
    unassigned_appointments = Appointment.objects.filter(doctor__isnull=True).order_by(
        "date", "time"
    )
    patients = Patient.objects.filter(added_by=user)
    return render(
        request,
        "doctor/dashboard.html",
        {
            "user": user,
            "appointments": appointments,
            "unassigned_appointments": unassigned_appointments,
            "patients": patients,
        },
    )


def doctor_accept_appointment(request, appointment_id):
    user = get_current_doctor(request)
    if not user or user.role != "Doctor":
        return redirect("login")

    if request.method == "POST":
        appointment = Appointment.objects.filter(id=appointment_id).first()
        if not appointment:
            messages.error(request, "Item not found.")
            return redirect("home")
        if appointment.doctor is None:
            appointment.doctor = user
            appointment.save()
            messages.success(
                request,
                f"You have claimed the appointment for {appointment.patient_name}.",
            )
        else:
            messages.error(request, "This appointment has already been claimed.")

    return redirect("doctor_dashboard")


def doctor_complete_appointment(request, appointment_id):
    user = get_current_doctor(request)
    if not user or user.role != "Doctor":
        return redirect("login")

    if request.method == "POST":
        appointment = Appointment.objects.filter(id=appointment_id, doctor=user).first()
        if not appointment:
            messages.error(request, "Item not found.")
            return redirect("home")
        if appointment.status != "Completed":
            appointment.status = "Completed"
            appointment.save()

            # Auto-create patient
            Patient.objects.get_or_create(
                name=appointment.patient_name,
                phone=appointment.phone,
                added_by=user,
                defaults={
                    "age": appointment.age,
                    "gender": appointment.gender,
                    "address": appointment.address,
                },
            )
            messages.success(
                request,
                f"Appointment completed. {appointment.patient_name} has been added to your patients.",
            )

    return redirect("doctor_dashboard")


def doctor_reject_appointment(request, appointment_id):
    user = get_current_doctor(request)
    if not user or user.role != "Doctor":
        return redirect("login")

    if request.method == "POST":
        appointment = Appointment.objects.filter(id=appointment_id, doctor=user).first()
        if not appointment:
            messages.error(request, "Item not found.")
            return redirect("home")
        if appointment.status != "Rejected":
            appointment.status = "Rejected"
            appointment.save()
            messages.success(
                request,
                f"Appointment for {appointment.patient_name} has been rejected.",
            )

    return redirect("doctor_dashboard")


def doctor_patients(request):
    user = get_current_doctor(request)
    if not user or user.role != "Doctor":
        return redirect("login")

    patients = Patient.objects.filter(added_by=user)

    q = request.GET.get("q")
    if q:
        patients = patients.filter(name__icontains=q)

    return render(
        request,
        "doctor/patients.html",
        {"user": user, "patients": patients, "search_query": q},
    )


def doctor_add_patient(request):
    user = get_current_doctor(request)
    if not user or user.role != "Doctor":
        return redirect("login")

    if request.method == "POST":
        name = request.POST.get("name")
        age = request.POST.get("age")
        gender = request.POST.get("gender")
        address = request.POST.get("address")
        phone = request.POST.get("phone")

        Patient.objects.create(
            name=name,
            age=age,
            gender=gender,
            address=address,
            phone=phone,
            added_by=user,
        )
        messages.success(request, "Patient added successfully!")
        return redirect("doctor_patients")

    return render(request, "doctor/add_patient.html", {"user": user})


def doctor_edit_patient(request, patient_id):
    user = get_current_doctor(request)
    if not user or user.role != "Doctor":
        return redirect("login")

    patient = Patient.objects.filter(id=patient_id, added_by=user).first()

    if not patient:

        messages.error(request, "Item not found.")

        return redirect("home")

    if request.method == "POST":
        patient.name = request.POST.get("name")
        patient.age = request.POST.get("age")
        patient.gender = request.POST.get("gender")
        patient.address = request.POST.get("address")
        patient.phone = request.POST.get("phone")
        patient.save()
        messages.success(request, "Patient updated successfully!")
        return redirect("doctor_patients")

    return render(
        request, "doctor/edit_patient.html", {"user": user, "patient": patient}
    )


def doctor_medical_records(request, patient_id):
    user = get_current_doctor(request)
    if not user or user.role != "Doctor":
        return redirect("login")

    patient = Patient.objects.filter(id=patient_id).first()

    if not patient:

        messages.error(request, "Item not found.")

        return redirect("home")
    records = MedicalRecord.objects.filter(patient=patient)

    if request.method == "POST":
        diagnosis = request.POST.get("diagnosis")
        prescription = request.POST.get("prescription")
        MedicalRecord.objects.create(
            patient=patient, doctor=user, diagnosis=diagnosis, prescription=prescription
        )
        messages.success(request, "Medical record added!")
        return redirect("doctor_medical_records", patient_id=patient.id)

    return render(
        request,
        "doctor/medical_records.html",
        {"user": user, "patient": patient, "records": records},
    )


# --- ADMIN VIEWS ---


def admin_dashboard(request):
    user = get_current_admin(request)
    if not user:
        return redirect("admin_login")

    context = {
        "user": user,
        "doctor_count": Doctor.objects.filter(role="Doctor").count(),
        "patient_count": Patient.objects.count(),
        "appointment_count": Appointment.objects.count(),
        "staff_count": Staff.objects.count(),
    }
    return render(request, "admin/dashboard.html", context)


def admin_doctors(request):
    user = get_current_admin(request)
    if not user:
        return redirect("admin_login")

    doctors = Doctor.objects.filter(role="Doctor")
    return render(request, "admin/doctors.html", {"user": user, "doctors": doctors})


def admin_approve_doctor(request, doctor_id):
    user = get_current_admin(request)
    if not user:
        return redirect("admin_login")

    doctor = Doctor.objects.filter(id=doctor_id, role="Doctor").first()

    if not doctor:

        messages.error(request, "Item not found.")

        return redirect("home")
    doctor.is_approved = not doctor.is_approved
    doctor.save()
    messages.success(request, f"Doctor {doctor.username} approval status updated.")
    return redirect("admin_doctors")


def admin_staff(request):
    user = get_current_admin(request)
    if not user:
        return redirect("admin_login")

    staff = Staff.objects.all()
    return render(request, "admin/staff.html", {"user": user, "staff": staff})


def admin_add_staff(request):
    user = get_current_admin(request)
    if not user:
        return redirect("admin_login")

    if request.method == "POST":
        name = request.POST.get("name")
        role_title = request.POST.get("role_title")
        phone = request.POST.get("phone")
        email = request.POST.get("email")

        Staff.objects.create(name=name, role_title=role_title, phone=phone, email=email)
        messages.success(request, "Staff member added successfully!")
        return redirect("admin_staff")

    return render(request, "admin/add_staff.html", {"user": user})


def admin_view_staff(request, staff_id):
    user = get_current_admin(request)
    if not user:
        return redirect("admin_login")

    staff_member = Staff.objects.filter(id=staff_id).first()

    if not staff_member:

        messages.error(request, "Item not found.")

        return redirect("home")
    return render(
        request, "admin/view_staff.html", {"user": user, "staff_member": staff_member}
    )


def admin_edit_staff(request, staff_id):
    user = get_current_admin(request)
    if not user:
        return redirect("admin_login")

    staff_member = Staff.objects.filter(id=staff_id).first()

    if not staff_member:

        messages.error(request, "Item not found.")

        return redirect("home")

    if request.method == "POST":
        staff_member.name = request.POST.get("name")
        staff_member.role_title = request.POST.get("role_title")
        staff_member.phone = request.POST.get("phone")
        staff_member.email = request.POST.get("email")
        staff_member.save()

        messages.success(request, "Staff member updated successfully!")
        return redirect("admin_staff")

    return render(
        request, "admin/edit_staff.html", {"user": user, "staff_member": staff_member}
    )


def admin_delete_staff(request, staff_id):
    user = get_current_admin(request)
    if not user:
        return redirect("admin_login")

    if request.method == "POST":
        staff_member = Staff.objects.filter(id=staff_id).first()
        if not staff_member:
            messages.error(request, "Item not found.")
            return redirect("home")
        staff_member.delete()
        messages.success(request, "Staff member deleted successfully!")

    return redirect("admin_staff")


def admin_patients(request):
    user = get_current_admin(request)
    if not user:
        return redirect("admin_login")

    patients = Patient.objects.all()

    q = request.GET.get("q")
    if q:
        from django.db.models import Q

        if q.isdigit():
            patients = patients.filter(Q(name__icontains=q) | Q(id=q))
        else:
            patients = patients.filter(name__icontains=q)

    return render(
        request,
        "admin/patients.html",
        {"user": user, "patients": patients, "search_query": q},
    )


def admin_appointments(request):
    user = get_current_admin(request)
    if not user:
        return redirect("admin_login")

    appointments = Appointment.objects.all().order_by("-date")

    if request.method == "POST":
        appointment_id = request.POST.get("appointment_id")
        status = request.POST.get("status")
        app = Appointment.objects.filter(id=appointment_id).first()
        if not app:
            messages.error(request, "Item not found.")
            return redirect("home")
        if status == "Completed" and app.status != "Completed":
            if app.doctor:
                Patient.objects.get_or_create(
                    name=app.patient_name,
                    phone=app.phone,
                    added_by=app.doctor,
                    defaults={
                        "age": app.age,
                        "gender": app.gender,
                        "address": app.address,
                    },
                )

        app.status = status
        app.save()
        messages.success(request, "Appointment status updated!")
        return redirect("admin_appointments")

    return render(
        request, "admin/appointments.html", {"user": user, "appointments": appointments}
    )


def admin_add_doctor(request):
    user = get_current_admin(request)
    if not user:
        return redirect("admin_login")

    if request.method == "POST":
        username = request.POST.get("username")
        email = request.POST.get("email")
        password = request.POST.get("password")
        specialization = request.POST.get("specialization")
        phone = request.POST.get("phone")

        if not re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$", email):
            messages.error(request, "Invalid email format!")
            return redirect("admin_add_doctor")

        if phone and not re.match(r"^\+?[0-9]{10,15}$", phone):
            messages.error(
                request,
                "Invalid phone number format. It should contain 10 to 15 digits.",
            )
            return redirect("admin_add_doctor")

        if not re.match(
            r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*#?&]).{8,}$", password
        ):
            messages.error(
                request,
                "Password must be at least 8 characters long, contain at least one uppercase letter, one lowercase letter, one number, and one special character.",
            )
            return redirect("admin_add_doctor")

        Doctor.objects.create(
            username=username,
            email=email,
            password=make_password(password),
            role="Doctor",
            specialization=specialization,
            phone=phone,
            is_approved=True,
        )
        messages.success(request, "Doctor added successfully!")
        return redirect("admin_doctors")

    return render(request, "admin/add_doctor.html", {"user": user})


def admin_view_doctor(request, doctor_id):
    user = get_current_admin(request)
    if not user:
        return redirect("admin_login")

    doctor = Doctor.objects.filter(id=doctor_id, role="Doctor").first()

    if not doctor:

        messages.error(request, "Item not found.")

        return redirect("home")
    return render(request, "admin/view_doctor.html", {"user": user, "doctor": doctor})


def admin_edit_doctor(request, doctor_id):
    user = get_current_admin(request)
    if not user:
        return redirect("admin_login")

    doctor = Doctor.objects.filter(id=doctor_id, role="Doctor").first()

    if not doctor:

        messages.error(request, "Item not found.")

        return redirect("home")
    if request.method == "POST":
        email = request.POST.get("email")
        phone = request.POST.get("phone")
        password = request.POST.get("password")

        if not re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$", email):
            messages.error(request, "Invalid email format!")
            return redirect("admin_edit_doctor", doctor_id=doctor.id)

        if phone and not re.match(r"^\+?[0-9]{10,15}$", phone):
            messages.error(
                request,
                "Invalid phone number format. It should contain 10 to 15 digits.",
            )
            return redirect("admin_edit_doctor", doctor_id=doctor.id)

        if password:
            if not re.match(
                r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*#?&]).{8,}$", password
            ):
                messages.error(
                    request,
                    "Password must be at least 8 characters long, contain at least one uppercase letter, one lowercase letter, one number, and one special character.",
                )
                return redirect("admin_edit_doctor", doctor_id=doctor.id)
            doctor.password = make_password(password)

        doctor.username = request.POST.get("username")
        doctor.email = email
        doctor.specialization = request.POST.get("specialization")
        doctor.phone = phone
        doctor.save()

        messages.success(request, "Doctor updated successfully!")
        return redirect("admin_doctors")

    return render(request, "admin/edit_doctor.html", {"user": user, "doctor": doctor})


def admin_delete_doctor(request, doctor_id):
    user = get_current_admin(request)
    if not user:
        return redirect("admin_login")

    if request.method == "POST":
        doctor = Doctor.objects.filter(id=doctor_id, role="Doctor").first()
        if not doctor:
            messages.error(request, "Item not found.")
            return redirect("home")
        doctor.delete()
        messages.success(request, "Doctor deleted successfully!")

    return redirect("admin_doctors")


def admin_add_patient(request):
    user = get_current_admin(request)
    if not user:
        return redirect("admin_login")

    doctors = Doctor.objects.filter(role="Doctor")

    if request.method == "POST":
        name = request.POST.get("name")
        age = request.POST.get("age")
        gender = request.POST.get("gender")
        phone = request.POST.get("phone")
        address = request.POST.get("address")
        doctor_id = request.POST.get("doctor_id")

        doctor = None
        if doctor_id:
            doctor = Doctor.objects.filter(id=doctor_id, role="Doctor").first()

        Patient.objects.create(
            name=name,
            age=age,
            gender=gender,
            phone=phone,
            address=address,
            added_by=doctor,
        )
        messages.success(request, "Patient added successfully!")
        return redirect("admin_patients")

    return render(request, "admin/add_patient.html", {"user": user, "doctors": doctors})


def admin_view_patient(request, patient_id):
    user = get_current_admin(request)
    if not user:
        return redirect("admin_login")

    patient = Patient.objects.filter(id=patient_id).first()

    if not patient:

        messages.error(request, "Item not found.")

        return redirect("home")
    return render(
        request, "admin/view_patient.html", {"user": user, "patient": patient}
    )


def admin_edit_patient(request, patient_id):
    user = get_current_admin(request)
    if not user:
        return redirect("admin_login")

    patient = Patient.objects.filter(id=patient_id).first()

    if not patient:

        messages.error(request, "Item not found.")

        return redirect("home")
    doctors = Doctor.objects.filter(role="Doctor")

    if request.method == "POST":
        patient.name = request.POST.get("name")
        patient.age = request.POST.get("age")
        patient.gender = request.POST.get("gender")
        patient.phone = request.POST.get("phone")
        patient.address = request.POST.get("address")
        doctor_id = request.POST.get("doctor_id")

        if doctor_id:
            patient.added_by = Doctor.objects.filter(
                id=doctor_id, role="Doctor"
            ).first()
        else:
            patient.added_by = None

        patient.save()
        messages.success(request, "Patient updated successfully!")
        return redirect("admin_patients")

    return render(
        request,
        "admin/edit_patient.html",
        {"user": user, "patient": patient, "doctors": doctors},
    )


def admin_delete_patient(request, patient_id):
    user = get_current_admin(request)
    if not user:
        return redirect("admin_login")

    if request.method == "POST":
        patient = Patient.objects.filter(id=patient_id).first()
        if not patient:
            messages.error(request, "Item not found.")
            return redirect("home")
        patient.delete()
        messages.success(request, "Patient deleted successfully!")

    return redirect("admin_patients")
