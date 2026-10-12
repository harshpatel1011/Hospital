"""
In-depth test suite for the Clinic Management app
(Doctors / Patients / Staff / Appointments / Medical Records).

Place this file next to models.py / views.py / urls.py in your app folder
(rename it to tests.py if you like) and run:

    python manage.py test <your_app_name> -v 2

Covers:
    * Models       - defaults, __str__, uniqueness, FK delete behaviour
    * URLs         - reverse() + resolve() for every named route
    * Helpers      - get_current_doctor / get_current_admin
    * Doctor auth  - signup validation, login (approval gate), logout
    * Admin auth   - login/logout, session handling
    * Access ctrl  - anonymous + cross-role access to every protected view
    * Public       - home page, appointment booking
    * Doctor area  - dashboard, claim/complete/reject, patients, records
    * Admin area   - doctors, staff, patients, appointments CRUD
    * Workflow     - one end-to-end clinic scenario
    * Known issues - @expectedFailure tests documenting bugs found in views.py
"""
from datetime import date, time
from unittest import expectedFailure

from django.contrib.auth.hashers import check_password, make_password
from django.contrib.messages import get_messages
from django.db import IntegrityError, transaction
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import resolve, reverse

from . import views
from .models import Appointment, Doctor, MedicalRecord, Medisense, Patient, Staff

ADMIN_USERNAME = "Harsh"
ADMIN_PASSWORD = "Patel@123"
STRONG_PASSWORD = "Str0ng@Pass"

FAST_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
@override_settings(PASSWORD_HASHERS=FAST_HASHERS)  # keeps the suite fast
class BaseTestCase(TestCase):
    # ---- session helpers ---------------------------------------------------
    def login_admin(self, client=None):
        client = client or self.client
        session = client.session
        session["admin_id"] = 1
        session.save()

    def login_doctor(self, doctor, client=None):
        client = client or self.client
        session = client.session
        session["doctor_id"] = doctor.id
        session.save()

    # ---- factories ---------------------------------------------------------
    def make_doctor(self, username="drsmith", approved=True, role="Doctor", **kwargs):
        defaults = dict(
            username=username,
            email=f"{username}@example.com",
            password=make_password(STRONG_PASSWORD),
            role=role,
            specialization="Cardiology",
            phone="9876543210",
            is_approved=approved,
        )
        defaults.update(kwargs)
        return Doctor.objects.create(**defaults)

    def make_patient(self, name="Alice", doctor=None, **kwargs):
        defaults = dict(
            name=name, age=30, gender="Female", address="12 Main St",
            phone="9000000001", added_by=doctor,
        )
        defaults.update(kwargs)
        return Patient.objects.create(**defaults)

    def make_staff(self, name="Nina", **kwargs):
        defaults = dict(
            name=name, role_title="Nurse", phone="9000000002", email=f"{name.lower()}@clinic.com"
        )
        defaults.update(kwargs)
        return Staff.objects.create(**defaults)

    def make_appt(self, doctor=None, patient_name="Pat Ient", **kwargs):
        defaults = dict(
            patient_name=patient_name, age=40, gender="Male", address="5 Elm Rd",
            phone="9000000003", date=date(2030, 1, 15), time=time(10, 30),
            doctor=doctor, reason="Checkup",
        )
        defaults.update(kwargs)
        return Appointment.objects.create(**defaults)

    # ---- message helpers ---------------------------------------------------
    def flash_messages(self, response):
        return [(m.level_tag, str(m)) for m in get_messages(response.wsgi_request)]

    def assertFlash(self, response, level, fragment):
        msgs = self.flash_messages(response)
        self.assertTrue(
            any(lvl == level and fragment in text for lvl, text in msgs),
            f"Expected {level!r} message containing {fragment!r}, got {msgs}",
        )

    def assertRedirectsTo(self, response, name, **kwargs):
        self.assertRedirects(
            response, reverse(name, kwargs=kwargs or None), fetch_redirect_response=False
        )


# --------------------------------------------------------------------------- #
# MODEL TESTS
# --------------------------------------------------------------------------- #
class DoctorModelTests(BaseTestCase):
    def test_str(self):
        self.assertEqual(str(self.make_doctor("who")), "who (Doctor)")

    def test_defaults(self):
        d = Doctor.objects.create(
            username="x", email="x@x.com", password="p", specialization="s", phone="1"
        )
        self.assertEqual(d.role, "Doctor")
        self.assertFalse(d.is_approved)
        self.assertIsNotNone(d.created_at)

    def test_username_unique(self):
        self.make_doctor("dup")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_doctor("dup", email="other@example.com")

    def test_email_unique(self):
        self.make_doctor("a", email="same@example.com")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_doctor("b", email="same@example.com")

    def test_hashed_password_fits_in_column(self):
        self.assertLessEqual(
            len(make_password(STRONG_PASSWORD)), Doctor._meta.get_field("password").max_length
        )


class OtherModelStrTests(BaseTestCase):
    def test_patient_str(self):
        self.assertEqual(str(self.make_patient("Zed")), "Zed")

    def test_staff_str(self):
        self.assertEqual(str(self.make_staff("Nina", role_title="Nurse")), "Nina - Nurse")

    def test_appointment_str_and_defaults(self):
        a = Appointment.objects.create(
            patient_name="Bob", phone="1", date=date(2030, 2, 1), time=time(9, 0), reason="r"
        )
        self.assertEqual(str(a), "Appointment for Bob on 2030-02-01")
        self.assertEqual(a.status, "Pending")
        self.assertEqual(a.age, 0)
        self.assertEqual(a.gender, "Other")
        self.assertEqual(a.address, "")
        self.assertIsNone(a.doctor)

    def test_medical_record_str(self):
        p = self.make_patient("Zed")
        r = MedicalRecord.objects.create(patient=p, diagnosis="d", prescription="p")
        self.assertEqual(str(r), f"Record for Zed on {r.date}")

    def test_medisense_str(self):
        p = self.make_patient("Zed")
        m = Medisense.objects.create(patient=p, record_type="BP", value="120/80")
        self.assertEqual(str(m), "BP - 120/80 for Zed")

    def test_choices(self):
        self.assertEqual([c[0] for c in Patient.GENDER_CHOICES], ["Male", "Female", "Other"])
        self.assertEqual(
            [c[0] for c in Appointment.STATUS_CHOICES], ["Pending", "Completed", "Rejected"]
        )


class ForeignKeyBehaviourTests(BaseTestCase):
    def test_deleting_doctor_keeps_related_rows_with_null_fk(self):
        doc = self.make_doctor()
        patient = self.make_patient(doctor=doc)
        appt = self.make_appt(doctor=doc)
        rec = MedicalRecord.objects.create(patient=patient, doctor=doc, diagnosis="d", prescription="p")
        doc.delete()
        for obj in (patient, appt, rec):
            obj.refresh_from_db()
        self.assertIsNone(patient.added_by)
        self.assertIsNone(appt.doctor)
        self.assertIsNone(rec.doctor)

    def test_deleting_patient_cascades_to_records_and_medisense(self):
        patient = self.make_patient()
        MedicalRecord.objects.create(patient=patient, diagnosis="d", prescription="p")
        Medisense.objects.create(patient=patient, record_type="HR", value="70")
        patient.delete()
        self.assertEqual(MedicalRecord.objects.count(), 0)
        self.assertEqual(Medisense.objects.count(), 0)

    def test_related_names(self):
        doc = self.make_doctor()
        patient = self.make_patient(doctor=doc)
        appt = self.make_appt(doctor=doc)
        rec = MedicalRecord.objects.create(patient=patient, doctor=doc, diagnosis="d", prescription="p")
        med = Medisense.objects.create(patient=patient, record_type="HR", value="70")
        self.assertIn(patient, doc.added_patients.all())
        self.assertIn(appt, doc.appointments.all())
        self.assertIn(rec, doc.medical_records.all())
        self.assertIn(rec, patient.medical_records.all())
        self.assertIn(med, patient.medisense_records.all())


# --------------------------------------------------------------------------- #
# URL TESTS
# --------------------------------------------------------------------------- #
class UrlTests(BaseTestCase):
    def test_named_routes_resolve_to_expected_views(self):
        cases = [
            ("home", {}, views.home),
            ("book_appointment", {}, views.book_appointment),
            ("login", {}, views.doctor_login),
            ("signup", {}, views.doctor_signup),
            ("logout", {}, views.doctor_logout),
            ("admin_login", {}, views.admin_login),
            ("admin_logout", {}, views.admin_logout),
            ("doctor_dashboard", {}, views.doctor_dashboard),
            ("doctor_patients", {}, views.doctor_patients),
            ("doctor_add_patient", {}, views.doctor_add_patient),
            ("doctor_edit_patient", {"patient_id": 1}, views.doctor_edit_patient),
            ("doctor_medical_records", {"patient_id": 1}, views.doctor_medical_records),
            ("doctor_accept_appointment", {"appointment_id": 1}, views.doctor_accept_appointment),
            ("doctor_complete_appointment", {"appointment_id": 1}, views.doctor_complete_appointment),
            ("doctor_reject_appointment", {"appointment_id": 1}, views.doctor_reject_appointment),
            ("admin_dashboard", {}, views.admin_dashboard),
            ("admin_doctors", {}, views.admin_doctors),
            ("admin_add_doctor", {}, views.admin_add_doctor),
            ("admin_view_doctor", {"doctor_id": 1}, views.admin_view_doctor),
            ("admin_edit_doctor", {"doctor_id": 1}, views.admin_edit_doctor),
            ("admin_delete_doctor", {"doctor_id": 1}, views.admin_delete_doctor),
            ("admin_approve_doctor", {"doctor_id": 1}, views.admin_approve_doctor),
            ("admin_staff", {}, views.admin_staff),
            ("admin_add_staff", {}, views.admin_add_staff),
            ("admin_view_staff", {"staff_id": 1}, views.admin_view_staff),
            ("admin_edit_staff", {"staff_id": 1}, views.admin_edit_staff),
            ("admin_delete_staff", {"staff_id": 1}, views.admin_delete_staff),
            ("admin_patients", {}, views.admin_patients),
            ("admin_add_patient", {}, views.admin_add_patient),
            ("admin_view_patient", {"patient_id": 1}, views.admin_view_patient),
            ("admin_edit_patient", {"patient_id": 1}, views.admin_edit_patient),
            ("admin_delete_patient", {"patient_id": 1}, views.admin_delete_patient),
            ("admin_appointments", {}, views.admin_appointments),
        ]
        for name, kwargs, view in cases:
            with self.subTest(route=name):
                self.assertIs(resolve(reverse(name, kwargs=kwargs)).func, view)

    def test_non_integer_ids_are_404(self):
        url = reverse("admin_view_doctor", kwargs={"doctor_id": 1}).replace("/1/", "/abc/")
        self.assertEqual(self.client.get(url).status_code, 404)


# --------------------------------------------------------------------------- #
# SESSION HELPER FUNCTIONS
# --------------------------------------------------------------------------- #
class SessionHelperTests(BaseTestCase):
    def _request(self, **session):
        request = RequestFactory().get("/")
        request.session = session
        return request

    def test_get_current_admin(self):
        self.assertEqual(
            views.get_current_admin(self._request(admin_id=1)),
            {"id": 1, "username": "Harsh", "role": "Admin"},
        )
        self.assertIsNotNone(views.get_current_admin(self._request(admin_id="1")))
        self.assertIsNone(views.get_current_admin(self._request(admin_id=2)))
        self.assertIsNone(views.get_current_admin(self._request()))

    def test_get_current_doctor(self):
        doc = self.make_doctor()
        self.assertEqual(views.get_current_doctor(self._request(doctor_id=doc.id)), doc)
        self.assertIsNone(views.get_current_doctor(self._request()))
        self.assertIsNone(views.get_current_doctor(self._request(doctor_id=99999)))


# --------------------------------------------------------------------------- #
# DOCTOR SIGNUP
# --------------------------------------------------------------------------- #
class DoctorSignupTests(BaseTestCase):
    def payload(self, **overrides):
        data = {
            "username": "newdoc",
            "email": "newdoc@example.com",
            "password": STRONG_PASSWORD,
            "password_confirm": STRONG_PASSWORD,
            "specialization": "Neurology",
            "phone": "9876543210",
        }
        data.update(overrides)
        return data

    def test_get_renders_form(self):
        resp = self.client.get(reverse("signup"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "doctor/signup.html")

    def test_logged_in_doctor_redirected_home(self):
        self.login_doctor(self.make_doctor())
        self.assertRedirectsTo(self.client.get(reverse("signup")), "home")

    def test_successful_signup_creates_unapproved_hashed_doctor(self):
        resp = self.client.post(reverse("signup"), self.payload())
        self.assertRedirectsTo(resp, "login")
        doc = Doctor.objects.get(username="newdoc")
        self.assertEqual(doc.role, "Doctor")
        self.assertFalse(doc.is_approved)
        self.assertEqual(doc.specialization, "Neurology")
        self.assertNotEqual(doc.password, STRONG_PASSWORD)
        self.assertTrue(check_password(STRONG_PASSWORD, doc.password))
        self.assertFlash(resp, "success", "wait for Admin approval")

    def test_signup_does_not_log_the_user_in(self):
        self.client.post(reverse("signup"), self.payload())
        self.assertNotIn("doctor_id", self.client.session)

    def test_phone_is_optional(self):
        resp = self.client.post(reverse("signup"), self.payload(phone=""))
        self.assertRedirectsTo(resp, "login")
        self.assertEqual(Doctor.objects.get(username="newdoc").phone, "")

    def test_international_phone_accepted(self):
        self.client.post(reverse("signup"), self.payload(phone="+919876543210"))
        self.assertTrue(Doctor.objects.filter(username="newdoc").exists())

    def test_invalid_emails_rejected(self):
        for bad in ["plainaddress", "a@b", "@x.com", "a b@x.com"]:
            with self.subTest(email=bad):
                resp = self.client.post(reverse("signup"), self.payload(email=bad))
                self.assertRedirectsTo(resp, "signup")
                self.assertFlash(resp, "error", "Invalid email format")
        self.assertEqual(Doctor.objects.count(), 0)

    def test_invalid_phones_rejected(self):
        for bad in ["12345", "98765abcde", "1" * 16, "++919876543210"]:
            with self.subTest(phone=bad):
                resp = self.client.post(reverse("signup"), self.payload(phone=bad))
                self.assertRedirectsTo(resp, "signup")
                self.assertFlash(resp, "error", "Invalid phone number")
        self.assertEqual(Doctor.objects.count(), 0)

    def test_weak_passwords_rejected(self):
        weak = ["Sh0rt@", "nouppercase1@", "NOLOWERCASE1@", "NoDigits@@@", "NoSpecial123"]
        for pw in weak:
            with self.subTest(password=pw):
                resp = self.client.post(
                    reverse("signup"), self.payload(password=pw, password_confirm=pw)
                )
                self.assertRedirectsTo(resp, "signup")
                self.assertFlash(resp, "error", "Password must be at least 8 characters")
        self.assertEqual(Doctor.objects.count(), 0)

    def test_password_mismatch(self):
        resp = self.client.post(reverse("signup"), self.payload(password_confirm="Different1@"))
        self.assertRedirectsTo(resp, "signup")
        self.assertFlash(resp, "error", "Passwords do not match")
        self.assertEqual(Doctor.objects.count(), 0)

    def test_duplicate_username(self):
        self.make_doctor("newdoc")
        resp = self.client.post(reverse("signup"), self.payload())
        self.assertRedirectsTo(resp, "signup")
        self.assertFlash(resp, "error", "Username already taken")
        self.assertEqual(Doctor.objects.count(), 1)

    def test_duplicate_email(self):
        self.make_doctor("someoneelse", email="newdoc@example.com")
        resp = self.client.post(reverse("signup"), self.payload())
        self.assertRedirectsTo(resp, "signup")
        self.assertFlash(resp, "error", "Email already registered")
        self.assertEqual(Doctor.objects.count(), 1)


# --------------------------------------------------------------------------- #
# DOCTOR LOGIN / LOGOUT
# --------------------------------------------------------------------------- #
class DoctorLoginTests(BaseTestCase):
    def test_get_renders_form(self):
        resp = self.client.get(reverse("login"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "doctor/login.html")

    def test_success_sets_session_and_redirects_to_dashboard(self):
        doc = self.make_doctor()
        resp = self.client.post(reverse("login"), {"username": "drsmith", "password": STRONG_PASSWORD})
        self.assertRedirectsTo(resp, "doctor_dashboard")
        self.assertEqual(self.client.session["doctor_id"], doc.id)
        self.assertFlash(resp, "success", "Welcome back, Dr. drsmith")

    def test_wrong_password_rerenders_form(self):
        self.make_doctor()
        resp = self.client.post(reverse("login"), {"username": "drsmith", "password": "wrong"})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("doctor_id", self.client.session)
        self.assertFlash(resp, "error", "Invalid password")

    def test_unknown_username_redirects_back(self):
        resp = self.client.post(reverse("login"), {"username": "ghost", "password": STRONG_PASSWORD})
        self.assertRedirectsTo(resp, "login")
        self.assertFlash(resp, "error", "Invalid username or you are not a Doctor")

    def test_unapproved_doctor_cannot_login(self):
        self.make_doctor(approved=False)
        resp = self.client.post(reverse("login"), {"username": "drsmith", "password": STRONG_PASSWORD})
        self.assertRedirectsTo(resp, "login")
        self.assertNotIn("doctor_id", self.client.session)
        self.assertFlash(resp, "error", "pending admin approval")

    def test_non_doctor_role_cannot_login(self):
        self.make_doctor("boss", role="Admin")
        resp = self.client.post(reverse("login"), {"username": "boss", "password": STRONG_PASSWORD})
        self.assertRedirectsTo(resp, "login")
        self.assertNotIn("doctor_id", self.client.session)

    def test_missing_password_does_not_login(self):
        self.make_doctor()
        resp = self.client.post(reverse("login"), {"username": "drsmith"})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("doctor_id", self.client.session)

    def test_username_is_case_sensitive_on_lookup(self):
        self.make_doctor("drsmith")
        resp = self.client.post(reverse("login"), {"username": "DRSMITH", "password": STRONG_PASSWORD})
        self.assertNotIn("doctor_id", self.client.session)
        self.assertRedirectsTo(resp, "login")

    def test_already_logged_in_redirects_home(self):
        self.login_doctor(self.make_doctor())
        self.assertRedirectsTo(self.client.get(reverse("login")), "home")

    def test_logout_clears_session(self):
        self.login_doctor(self.make_doctor())
        resp = self.client.get(reverse("logout"))
        self.assertRedirectsTo(resp, "home")
        self.assertNotIn("doctor_id", self.client.session)
        self.assertFlash(resp, "success", "Successfully logged out")

    def test_logout_when_anonymous_is_harmless(self):
        self.assertRedirectsTo(self.client.get(reverse("logout")), "home")

    def test_logout_leaves_admin_session_intact(self):
        self.login_admin()
        self.login_doctor(self.make_doctor())
        self.client.get(reverse("logout"))
        self.assertEqual(self.client.session.get("admin_id"), 1)

    def test_deleted_doctor_with_live_session_is_treated_as_anonymous(self):
        doc = self.make_doctor()
        self.login_doctor(doc)
        doc.delete()
        self.assertRedirectsTo(self.client.get(reverse("doctor_dashboard")), "login")

    def test_non_doctor_role_in_session_cannot_use_doctor_area(self):
        boss = self.make_doctor("boss", role="Admin")
        self.login_doctor(boss)
        self.assertRedirectsTo(self.client.get(reverse("doctor_dashboard")), "login")


# --------------------------------------------------------------------------- #
# ADMIN LOGIN / LOGOUT
# --------------------------------------------------------------------------- #
class AdminLoginTests(BaseTestCase):
    def test_get_renders_form(self):
        resp = self.client.get(reverse("admin_login"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "admin/login.html")

    def test_success(self):
        resp = self.client.post(
            reverse("admin_login"), {"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
        )
        self.assertRedirectsTo(resp, "admin_dashboard")
        self.assertEqual(self.client.session["admin_id"], 1)
        self.assertFlash(resp, "success", "Welcome back Admin Harsh")

    def test_bad_credentials(self):
        for creds in [
            {"username": ADMIN_USERNAME, "password": "nope"},
            {"username": "harsh", "password": ADMIN_PASSWORD},
            {"username": "", "password": ""},
            {},
        ]:
            with self.subTest(creds=creds):
                resp = self.client.post(reverse("admin_login"), creds)
                self.assertEqual(resp.status_code, 200)
                self.assertNotIn("admin_id", self.client.session)
                self.assertFlash(resp, "error", "Invalid admin credentials")

    def test_doctor_credentials_do_not_work_as_admin(self):
        self.make_doctor()
        resp = self.client.post(
            reverse("admin_login"), {"username": "drsmith", "password": STRONG_PASSWORD}
        )
        self.assertNotIn("admin_id", self.client.session)
        self.assertEqual(resp.status_code, 200)

    def test_already_logged_in_redirects_to_dashboard(self):
        self.login_admin()
        self.assertRedirectsTo(self.client.get(reverse("admin_login")), "admin_dashboard")

    def test_string_session_value_is_accepted(self):
        session = self.client.session
        session["admin_id"] = "1"
        session.save()
        self.assertEqual(self.client.get(reverse("admin_dashboard")).status_code, 200)

    def test_wrong_session_value_is_rejected(self):
        session = self.client.session
        session["admin_id"] = 2
        session.save()
        self.assertRedirectsTo(self.client.get(reverse("admin_dashboard")), "admin_login")

    def test_logout(self):
        self.login_admin()
        resp = self.client.get(reverse("admin_logout"))
        self.assertRedirectsTo(resp, "admin_login")
        self.assertNotIn("admin_id", self.client.session)
        self.assertFlash(resp, "success", "Admin successfully logged out")

    def test_logout_when_anonymous_is_harmless(self):
        self.assertRedirectsTo(self.client.get(reverse("admin_logout")), "admin_login")

    def test_admin_logout_leaves_doctor_session_intact(self):
        doc = self.make_doctor()
        self.login_admin()
        self.login_doctor(doc)
        self.client.get(reverse("admin_logout"))
        self.assertEqual(self.client.session.get("doctor_id"), doc.id)


# --------------------------------------------------------------------------- #
# ACCESS CONTROL (every protected route)
# --------------------------------------------------------------------------- #
class AccessControlTests(BaseTestCase):
    def setUp(self):
        self.doc = self.make_doctor()
        self.patient = self.make_patient(doctor=self.doc)
        self.appt = self.make_appt(doctor=self.doc)
        self.staff = self.make_staff()

    def doctor_urls(self):
        return [
            reverse("doctor_dashboard"),
            reverse("doctor_patients"),
            reverse("doctor_add_patient"),
            reverse("doctor_edit_patient", args=[self.patient.id]),
            reverse("doctor_medical_records", args=[self.patient.id]),
            reverse("doctor_accept_appointment", args=[self.appt.id]),
            reverse("doctor_complete_appointment", args=[self.appt.id]),
            reverse("doctor_reject_appointment", args=[self.appt.id]),
        ]

    def admin_urls(self):
        return [
            reverse("admin_dashboard"),
            reverse("admin_doctors"),
            reverse("admin_add_doctor"),
            reverse("admin_view_doctor", args=[self.doc.id]),
            reverse("admin_edit_doctor", args=[self.doc.id]),
            reverse("admin_delete_doctor", args=[self.doc.id]),
            reverse("admin_approve_doctor", args=[self.doc.id]),
            reverse("admin_staff"),
            reverse("admin_add_staff"),
            reverse("admin_view_staff", args=[self.staff.id]),
            reverse("admin_edit_staff", args=[self.staff.id]),
            reverse("admin_delete_staff", args=[self.staff.id]),
            reverse("admin_patients"),
            reverse("admin_add_patient"),
            reverse("admin_view_patient", args=[self.patient.id]),
            reverse("admin_edit_patient", args=[self.patient.id]),
            reverse("admin_delete_patient", args=[self.patient.id]),
            reverse("admin_appointments"),
        ]

    def test_anonymous_is_redirected_from_doctor_area(self):
        for url in self.doctor_urls():
            with self.subTest(url=url):
                self.assertRedirectsTo(self.client.get(url), "login")

    def test_anonymous_is_redirected_from_admin_area(self):
        for url in self.admin_urls():
            with self.subTest(url=url):
                self.assertRedirectsTo(self.client.get(url), "admin_login")

    def test_doctor_session_cannot_reach_admin_area(self):
        self.login_doctor(self.doc)
        for url in self.admin_urls():
            with self.subTest(url=url):
                self.assertRedirectsTo(self.client.get(url), "admin_login")

    def test_admin_session_cannot_reach_doctor_area(self):
        self.login_admin()
        for url in self.doctor_urls():
            with self.subTest(url=url):
                self.assertRedirectsTo(self.client.get(url), "login")

    def test_anonymous_post_cannot_mutate_anything(self):
        self.client.post(reverse("admin_delete_doctor", args=[self.doc.id]))
        self.client.post(reverse("admin_delete_patient", args=[self.patient.id]))
        self.client.post(reverse("admin_delete_staff", args=[self.staff.id]))
        self.client.post(reverse("admin_approve_doctor", args=[self.doc.id]))
        self.client.post(reverse("doctor_reject_appointment", args=[self.appt.id]))
        self.client.post(reverse("doctor_complete_appointment", args=[self.appt.id]))
        self.client.post(
            reverse("admin_appointments"), {"appointment_id": self.appt.id, "status": "Completed"}
        )
        self.client.post(reverse("admin_add_staff"), {"name": "x", "role_title": "y", "phone": "1", "email": "x@x.com"})

        self.assertTrue(Doctor.objects.filter(pk=self.doc.pk, is_approved=True).exists())
        self.assertTrue(Patient.objects.filter(pk=self.patient.pk).exists())
        self.assertTrue(Staff.objects.filter(pk=self.staff.pk).exists())
        self.assertEqual(Staff.objects.count(), 1)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.status, "Pending")


# --------------------------------------------------------------------------- #
# PUBLIC VIEWS
# --------------------------------------------------------------------------- #
class HomeViewTests(BaseTestCase):
    def test_home_anonymous(self):
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "index.html")
        self.assertIsNone(resp.context["user"])

    def test_home_with_logged_in_doctor(self):
        doc = self.make_doctor()
        self.login_doctor(doc)
        self.assertEqual(self.client.get(reverse("home")).context["user"], doc)


class BookAppointmentTests(BaseTestCase):
    def payload(self, **overrides):
        data = {
            "patient_name": "Walk In",
            "age": "35",
            "gender": "Male",
            "address": "7 Oak Ave",
            "phone": "9111111111",
            "date": "2030-03-20",
            "time": "14:45",
            "reason": "Back pain",
        }
        data.update(overrides)
        return data

    def test_get_lists_only_approved_doctors(self):
        approved = self.make_doctor("ok", approved=True)
        self.make_doctor("pending", approved=False)
        self.make_doctor("boss", role="Admin")
        resp = self.client.get(reverse("book_appointment"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "book_appointment.html")
        self.assertEqual(list(resp.context["doctors"]), [approved])

    def test_booking_without_doctor_creates_unassigned_pending_appointment(self):
        resp = self.client.post(reverse("book_appointment"), self.payload())
        self.assertRedirectsTo(resp, "home")
        a = Appointment.objects.get()
        self.assertEqual(a.patient_name, "Walk In")
        self.assertEqual(a.age, 35)
        self.assertEqual(a.gender, "Male")
        self.assertEqual(a.address, "7 Oak Ave")
        self.assertEqual(a.phone, "9111111111")
        self.assertEqual(a.date, date(2030, 3, 20))
        self.assertEqual(a.time, time(14, 45))
        self.assertEqual(a.reason, "Back pain")
        self.assertEqual(a.status, "Pending")
        self.assertIsNone(a.doctor)
        self.assertFlash(resp, "success", "Appointment booked successfully")

    def test_booking_with_valid_doctor_assigns_doctor(self):
        doc = self.make_doctor()
        self.client.post(reverse("book_appointment"), self.payload(doctor=doc.id))
        self.assertEqual(Appointment.objects.get().doctor, doc)

    def test_booking_with_unknown_doctor_id_leaves_unassigned(self):
        self.client.post(reverse("book_appointment"), self.payload(doctor=99999))
        self.assertIsNone(Appointment.objects.get().doctor)

    def test_booking_with_non_doctor_role_leaves_unassigned(self):
        boss = self.make_doctor("boss", role="Admin")
        self.client.post(reverse("book_appointment"), self.payload(doctor=boss.id))
        self.assertIsNone(Appointment.objects.get().doctor)

    def test_booking_needs_no_login(self):
        self.assertEqual(self.client.get(reverse("book_appointment")).status_code, 200)

    def test_multiple_bookings_are_independent(self):
        self.client.post(reverse("book_appointment"), self.payload(patient_name="A"))
        self.client.post(reverse("book_appointment"), self.payload(patient_name="B"))
        self.assertEqual(Appointment.objects.count(), 2)


# --------------------------------------------------------------------------- #
# DOCTOR AREA
# --------------------------------------------------------------------------- #
class DoctorDashboardTests(BaseTestCase):
    def setUp(self):
        self.doc = self.make_doctor("drone")
        self.other = self.make_doctor("drtwo")
        self.login_doctor(self.doc)

    def test_dashboard_context(self):
        mine_old = self.make_appt(self.doc, "Old", date=date(2030, 1, 1))
        mine_new = self.make_appt(self.doc, "New", date=date(2030, 6, 1))
        self.make_appt(self.other, "Theirs")
        free_late = self.make_appt(None, "FreeLate", date=date(2030, 5, 1), time=time(15, 0))
        free_early = self.make_appt(None, "FreeEarly", date=date(2030, 5, 1), time=time(9, 0))
        my_patient = self.make_patient("Mine", self.doc)
        self.make_patient("NotMine", self.other)

        resp = self.client.get(reverse("doctor_dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "doctor/dashboard.html")
        self.assertEqual(resp.context["user"], self.doc)
        self.assertEqual(list(resp.context["appointments"]), [mine_new, mine_old])
        self.assertEqual(list(resp.context["unassigned_appointments"]), [free_early, free_late])
        self.assertEqual(list(resp.context["patients"]), [my_patient])


class DoctorAppointmentActionTests(BaseTestCase):
    def setUp(self):
        self.doc = self.make_doctor("drone")
        self.other = self.make_doctor("drtwo")
        self.login_doctor(self.doc)

    # ---- accept / claim ----------------------------------------------------
    def test_accept_claims_unassigned_appointment(self):
        appt = self.make_appt(None, "Claimable")
        resp = self.client.post(reverse("doctor_accept_appointment", args=[appt.id]))
        self.assertRedirectsTo(resp, "doctor_dashboard")
        appt.refresh_from_db()
        self.assertEqual(appt.doctor, self.doc)
        self.assertEqual(appt.status, "Pending")
        self.assertFlash(resp, "success", "claimed the appointment for Claimable")

    def test_accept_cannot_steal_other_doctors_appointment(self):
        appt = self.make_appt(self.other)
        resp = self.client.post(reverse("doctor_accept_appointment", args=[appt.id]))
        self.assertRedirectsTo(resp, "doctor_dashboard")
        appt.refresh_from_db()
        self.assertEqual(appt.doctor, self.other)
        self.assertFlash(resp, "error", "already been claimed")

    def test_accept_own_appointment_again_reports_already_claimed(self):
        appt = self.make_appt(self.doc)
        resp = self.client.post(reverse("doctor_accept_appointment", args=[appt.id]))
        self.assertFlash(resp, "error", "already been claimed")

    def test_accept_get_does_nothing(self):
        appt = self.make_appt(None)
        resp = self.client.get(reverse("doctor_accept_appointment", args=[appt.id]))
        self.assertRedirectsTo(resp, "doctor_dashboard")
        appt.refresh_from_db()
        self.assertIsNone(appt.doctor)

    def test_accept_unknown_appointment(self):
        resp = self.client.post(reverse("doctor_accept_appointment", args=[99999]))
        self.assertRedirectsTo(resp, "home")
        self.assertFlash(resp, "error", "Item not found")

    # ---- complete ----------------------------------------------------------
    def test_complete_marks_completed_and_creates_patient(self):
        appt = self.make_appt(self.doc, "Pat Ient", age=52, gender="Male", address="9 Road", phone="9222222222")
        resp = self.client.post(reverse("doctor_complete_appointment", args=[appt.id]))
        self.assertRedirectsTo(resp, "doctor_dashboard")
        appt.refresh_from_db()
        self.assertEqual(appt.status, "Completed")

        patient = Patient.objects.get()
        self.assertEqual(patient.name, "Pat Ient")
        self.assertEqual(patient.phone, "9222222222")
        self.assertEqual(patient.age, 52)
        self.assertEqual(patient.gender, "Male")
        self.assertEqual(patient.address, "9 Road")
        self.assertEqual(patient.added_by, self.doc)
        self.assertFlash(resp, "success", "Pat Ient has been added to your patients")

    def test_complete_does_not_duplicate_existing_patient(self):
        self.make_patient("Pat Ient", self.doc, phone="9000000003")
        appt = self.make_appt(self.doc, "Pat Ient", phone="9000000003")
        self.client.post(reverse("doctor_complete_appointment", args=[appt.id]))
        self.assertEqual(Patient.objects.count(), 1)

    def test_complete_twice_is_idempotent(self):
        appt = self.make_appt(self.doc)
        url = reverse("doctor_complete_appointment", args=[appt.id])
        self.client.post(url)
        resp = self.client.post(url)
        self.assertRedirectsTo(resp, "doctor_dashboard")
        self.assertEqual(Patient.objects.count(), 1)
        self.assertEqual(self.flash_messages(resp), [])

    def test_complete_other_doctors_appointment_is_not_found(self):
        appt = self.make_appt(self.other)
        resp = self.client.post(reverse("doctor_complete_appointment", args=[appt.id]))
        self.assertRedirectsTo(resp, "home")
        self.assertFlash(resp, "error", "Item not found")
        appt.refresh_from_db()
        self.assertEqual(appt.status, "Pending")
        self.assertEqual(Patient.objects.count(), 0)

    def test_complete_unassigned_appointment_is_not_found(self):
        appt = self.make_appt(None)
        resp = self.client.post(reverse("doctor_complete_appointment", args=[appt.id]))
        self.assertRedirectsTo(resp, "home")

    def test_complete_get_does_nothing(self):
        appt = self.make_appt(self.doc)
        self.client.get(reverse("doctor_complete_appointment", args=[appt.id]))
        appt.refresh_from_db()
        self.assertEqual(appt.status, "Pending")

    # ---- reject ------------------------------------------------------------
    def test_reject_marks_rejected(self):
        appt = self.make_appt(self.doc, "Nope")
        resp = self.client.post(reverse("doctor_reject_appointment", args=[appt.id]))
        self.assertRedirectsTo(resp, "doctor_dashboard")
        appt.refresh_from_db()
        self.assertEqual(appt.status, "Rejected")
        self.assertFlash(resp, "success", "Appointment for Nope has been rejected")
        self.assertEqual(Patient.objects.count(), 0)

    def test_reject_twice_is_idempotent(self):
        appt = self.make_appt(self.doc)
        url = reverse("doctor_reject_appointment", args=[appt.id])
        self.client.post(url)
        resp = self.client.post(url)
        self.assertEqual(self.flash_messages(resp), [])

    def test_reject_other_doctors_appointment_is_not_found(self):
        appt = self.make_appt(self.other)
        resp = self.client.post(reverse("doctor_reject_appointment", args=[appt.id]))
        self.assertRedirectsTo(resp, "home")
        appt.refresh_from_db()
        self.assertEqual(appt.status, "Pending")

    def test_reject_get_does_nothing(self):
        appt = self.make_appt(self.doc)
        self.client.get(reverse("doctor_reject_appointment", args=[appt.id]))
        appt.refresh_from_db()
        self.assertEqual(appt.status, "Pending")


class DoctorPatientTests(BaseTestCase):
    def setUp(self):
        self.doc = self.make_doctor("drone")
        self.other = self.make_doctor("drtwo")
        self.login_doctor(self.doc)

    def patient_payload(self, **overrides):
        data = {"name": "New Pat", "age": "28", "gender": "Female", "address": "1 St", "phone": "9333333333"}
        data.update(overrides)
        return data

    # ---- list / search -----------------------------------------------------
    def test_list_shows_only_own_patients(self):
        mine = self.make_patient("Mine", self.doc)
        self.make_patient("Theirs", self.other)
        self.make_patient("Orphan", None)
        resp = self.client.get(reverse("doctor_patients"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "doctor/patients.html")
        self.assertEqual(list(resp.context["patients"]), [mine])
        self.assertIsNone(resp.context["search_query"])

    def test_search_is_case_insensitive_and_scoped(self):
        self.make_patient("Alice Wonder", self.doc)
        self.make_patient("Bob", self.doc)
        self.make_patient("Alice Other", self.other)
        resp = self.client.get(reverse("doctor_patients"), {"q": "ALICE"})
        self.assertEqual([p.name for p in resp.context["patients"]], ["Alice Wonder"])
        self.assertEqual(resp.context["search_query"], "ALICE")

    def test_search_no_match(self):
        self.make_patient("Alice", self.doc)
        resp = self.client.get(reverse("doctor_patients"), {"q": "zzz"})
        self.assertEqual(len(resp.context["patients"]), 0)

    # ---- add ---------------------------------------------------------------
    def test_add_get_renders_form(self):
        resp = self.client.get(reverse("doctor_add_patient"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "doctor/add_patient.html")

    def test_add_creates_patient_owned_by_current_doctor(self):
        resp = self.client.post(reverse("doctor_add_patient"), self.patient_payload())
        self.assertRedirectsTo(resp, "doctor_patients")
        p = Patient.objects.get()
        self.assertEqual((p.name, p.age, p.gender, p.address, p.phone), ("New Pat", 28, "Female", "1 St", "9333333333"))
        self.assertEqual(p.added_by, self.doc)
        self.assertFlash(resp, "success", "Patient added successfully")

    # ---- edit --------------------------------------------------------------
    def test_edit_get_renders_form(self):
        p = self.make_patient("Mine", self.doc)
        resp = self.client.get(reverse("doctor_edit_patient", args=[p.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "doctor/edit_patient.html")
        self.assertEqual(resp.context["patient"], p)

    def test_edit_updates_patient(self):
        p = self.make_patient("Mine", self.doc)
        resp = self.client.post(
            reverse("doctor_edit_patient", args=[p.id]),
            self.patient_payload(name="Renamed", age="61", gender="Other", address="New", phone="9444444444"),
        )
        self.assertRedirectsTo(resp, "doctor_patients")
        p.refresh_from_db()
        self.assertEqual((p.name, p.age, p.gender, p.address, p.phone), ("Renamed", 61, "Other", "New", "9444444444"))
        self.assertEqual(p.added_by, self.doc)
        self.assertFlash(resp, "success", "Patient updated successfully")

    def test_cannot_edit_another_doctors_patient(self):
        p = self.make_patient("Theirs", self.other)
        resp = self.client.get(reverse("doctor_edit_patient", args=[p.id]))
        self.assertRedirectsTo(resp, "home")
        resp = self.client.post(
            reverse("doctor_edit_patient", args=[p.id]), self.patient_payload(name="Hacked")
        )
        self.assertRedirectsTo(resp, "home")
        p.refresh_from_db()
        self.assertEqual(p.name, "Theirs")

    def test_cannot_edit_unassigned_patient(self):
        p = self.make_patient("Orphan", None)
        self.assertRedirectsTo(self.client.get(reverse("doctor_edit_patient", args=[p.id])), "home")

    def test_edit_unknown_patient(self):
        resp = self.client.get(reverse("doctor_edit_patient", args=[99999]))
        self.assertRedirectsTo(resp, "home")
        self.assertFlash(resp, "error", "Item not found")


class DoctorMedicalRecordTests(BaseTestCase):
    def setUp(self):
        self.doc = self.make_doctor("drone")
        self.login_doctor(self.doc)
        self.patient = self.make_patient("Mine", self.doc)

    def test_get_lists_records_for_that_patient_only(self):
        mine = MedicalRecord.objects.create(patient=self.patient, doctor=self.doc, diagnosis="Flu", prescription="Rest")
        other_patient = self.make_patient("Other", self.doc)
        MedicalRecord.objects.create(patient=other_patient, doctor=self.doc, diagnosis="X", prescription="Y")
        resp = self.client.get(reverse("doctor_medical_records", args=[self.patient.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "doctor/medical_records.html")
        self.assertEqual(resp.context["patient"], self.patient)
        self.assertEqual(list(resp.context["records"]), [mine])

    def test_post_creates_record_attributed_to_current_doctor(self):
        resp = self.client.post(
            reverse("doctor_medical_records", args=[self.patient.id]),
            {"diagnosis": "Migraine", "prescription": "Ibuprofen 400mg"},
        )
        self.assertRedirectsTo(resp, "doctor_medical_records", patient_id=self.patient.id)
        rec = MedicalRecord.objects.get()
        self.assertEqual(rec.patient, self.patient)
        self.assertEqual(rec.doctor, self.doc)
        self.assertEqual(rec.diagnosis, "Migraine")
        self.assertEqual(rec.prescription, "Ibuprofen 400mg")
        self.assertFlash(resp, "success", "Medical record added")

    def test_unknown_patient(self):
        resp = self.client.get(reverse("doctor_medical_records", args=[99999]))
        self.assertRedirectsTo(resp, "home")
        self.assertFlash(resp, "error", "Item not found")


# --------------------------------------------------------------------------- #
# ADMIN AREA
# --------------------------------------------------------------------------- #
class AdminDashboardTests(BaseTestCase):
    def test_counts(self):
        self.login_admin()
        d = self.make_doctor("d1")
        self.make_doctor("d2")
        self.make_doctor("boss", role="Admin")  # excluded from doctor_count
        self.make_patient("P1", d)
        self.make_patient("P2")
        self.make_patient("P3")
        self.make_appt()
        self.make_appt()
        self.make_staff()
        resp = self.client.get(reverse("admin_dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "admin/dashboard.html")
        ctx = resp.context
        self.assertEqual(ctx["doctor_count"], 2)
        self.assertEqual(ctx["patient_count"], 3)
        self.assertEqual(ctx["appointment_count"], 2)
        self.assertEqual(ctx["staff_count"], 1)
        self.assertEqual(ctx["user"]["username"], "Harsh")

    def test_counts_when_empty(self):
        self.login_admin()
        ctx = self.client.get(reverse("admin_dashboard")).context
        self.assertEqual((ctx["doctor_count"], ctx["patient_count"], ctx["appointment_count"], ctx["staff_count"]), (0, 0, 0, 0))


class AdminDoctorTests(BaseTestCase):
    def setUp(self):
        self.login_admin()

    def add_payload(self, **overrides):
        data = {
            "username": "newdoc", "email": "newdoc@example.com", "password": STRONG_PASSWORD,
            "specialization": "Dermatology", "phone": "9876543210",
        }
        data.update(overrides)
        return data

    # ---- list / view -------------------------------------------------------
    def test_list_shows_only_doctor_role(self):
        d = self.make_doctor("d1")
        self.make_doctor("boss", role="Admin")
        resp = self.client.get(reverse("admin_doctors"))
        self.assertTemplateUsed(resp, "admin/doctors.html")
        self.assertEqual(list(resp.context["doctors"]), [d])

    def test_view_doctor(self):
        d = self.make_doctor()
        resp = self.client.get(reverse("admin_view_doctor", args=[d.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "admin/view_doctor.html")
        self.assertEqual(resp.context["doctor"], d)

    def test_view_unknown_or_non_doctor_role(self):
        boss = self.make_doctor("boss", role="Admin")
        for pk in (99999, boss.id):
            with self.subTest(pk=pk):
                resp = self.client.get(reverse("admin_view_doctor", args=[pk]))
                self.assertRedirectsTo(resp, "home")
                self.assertFlash(resp, "error", "Item not found")

    # ---- add ---------------------------------------------------------------
    def test_add_get_renders_form(self):
        resp = self.client.get(reverse("admin_add_doctor"))
        self.assertTemplateUsed(resp, "admin/add_doctor.html")

    def test_add_creates_approved_doctor_with_hashed_password(self):
        resp = self.client.post(reverse("admin_add_doctor"), self.add_payload())
        self.assertRedirectsTo(resp, "admin_doctors")
        d = Doctor.objects.get(username="newdoc")
        self.assertTrue(d.is_approved)
        self.assertEqual(d.role, "Doctor")
        self.assertEqual(d.specialization, "Dermatology")
        self.assertNotEqual(d.password, STRONG_PASSWORD)
        self.assertTrue(check_password(STRONG_PASSWORD, d.password))
        self.assertFlash(resp, "success", "Doctor added successfully")

    def test_added_doctor_can_log_in_immediately(self):
        self.client.post(reverse("admin_add_doctor"), self.add_payload())
        other = Client()
        resp = other.post(reverse("login"), {"username": "newdoc", "password": STRONG_PASSWORD})
        self.assertRedirectsTo(resp, "doctor_dashboard")

    def test_add_validation_failures_redirect_back_without_creating(self):
        cases = [
            ("email", "bad-email", "Invalid email format"),
            ("phone", "123", "Invalid phone number"),
            ("password", "weak", "Password must be at least 8 characters"),
        ]
        for field, value, message in cases:
            with self.subTest(field=field):
                resp = self.client.post(reverse("admin_add_doctor"), self.add_payload(**{field: value}))
                self.assertRedirectsTo(resp, "admin_add_doctor")
                self.assertFlash(resp, "error", message)
        self.assertEqual(Doctor.objects.count(), 0)

    def test_add_allows_blank_phone(self):
        resp = self.client.post(reverse("admin_add_doctor"), self.add_payload(phone=""))
        self.assertRedirectsTo(resp, "admin_doctors")

    # ---- edit --------------------------------------------------------------
    def edit_payload(self, doctor, **overrides):
        data = {
            "username": doctor.username, "email": doctor.email, "phone": doctor.phone,
            "specialization": doctor.specialization, "password": "",
        }
        data.update(overrides)
        return data

    def test_edit_get_renders_form(self):
        d = self.make_doctor()
        resp = self.client.get(reverse("admin_edit_doctor", args=[d.id]))
        self.assertTemplateUsed(resp, "admin/edit_doctor.html")
        self.assertEqual(resp.context["doctor"], d)

    def test_edit_updates_fields_and_keeps_password_when_blank(self):
        d = self.make_doctor()
        old_hash = d.password
        resp = self.client.post(
            reverse("admin_edit_doctor", args=[d.id]),
            self.edit_payload(d, username="renamed", email="new@example.com", phone="9555555555", specialization="ENT"),
        )
        self.assertRedirectsTo(resp, "admin_doctors")
        d.refresh_from_db()
        self.assertEqual((d.username, d.email, d.phone, d.specialization), ("renamed", "new@example.com", "9555555555", "ENT"))
        self.assertEqual(d.password, old_hash)
        self.assertFlash(resp, "success", "Doctor updated successfully")

    def test_edit_with_new_password_rehashes(self):
        d = self.make_doctor()
        self.client.post(reverse("admin_edit_doctor", args=[d.id]), self.edit_payload(d, password="Brand#New1x"))
        d.refresh_from_db()
        self.assertTrue(check_password("Brand#New1x", d.password))
        self.assertFalse(check_password(STRONG_PASSWORD, d.password))

    def test_edit_validation_failures_do_not_save(self):
        d = self.make_doctor()
        cases = [
            ("email", "nope", "Invalid email format"),
            ("phone", "abc", "Invalid phone number"),
            ("password", "weak", "Password must be at least 8 characters"),
        ]
        for field, value, message in cases:
            with self.subTest(field=field):
                resp = self.client.post(
                    reverse("admin_edit_doctor", args=[d.id]),
                    self.edit_payload(d, username="shouldnotsave", **{field: value}),
                )
                self.assertRedirectsTo(resp, "admin_edit_doctor", doctor_id=d.id)
                self.assertFlash(resp, "error", message)
        d.refresh_from_db()
        self.assertEqual(d.username, "drsmith")

    def test_edit_unknown_doctor(self):
        resp = self.client.get(reverse("admin_edit_doctor", args=[99999]))
        self.assertRedirectsTo(resp, "home")

    # ---- approve -----------------------------------------------------------
    def test_approve_toggles_status(self):
        d = self.make_doctor(approved=False)
        url = reverse("admin_approve_doctor", args=[d.id])
        resp = self.client.post(url)
        self.assertRedirectsTo(resp, "admin_doctors")
        d.refresh_from_db()
        self.assertTrue(d.is_approved)
        self.assertFlash(resp, "success", "Doctor drsmith approval status updated")
        self.client.post(url)
        d.refresh_from_db()
        self.assertFalse(d.is_approved)

    def test_approved_doctor_can_then_log_in(self):
        d = self.make_doctor(approved=False)
        other = Client()
        creds = {"username": "drsmith", "password": STRONG_PASSWORD}
        other.post(reverse("login"), creds)
        self.assertNotIn("doctor_id", other.session)
        self.client.post(reverse("admin_approve_doctor", args=[d.id]))
        other.post(reverse("login"), creds)
        self.assertEqual(other.session["doctor_id"], d.id)

    def test_approve_unknown_doctor(self):
        resp = self.client.post(reverse("admin_approve_doctor", args=[99999]))
        self.assertRedirectsTo(resp, "home")
        self.assertFlash(resp, "error", "Item not found")

    # ---- delete ------------------------------------------------------------
    def test_delete_post_removes_doctor_but_keeps_their_data(self):
        d = self.make_doctor()
        p = self.make_patient(doctor=d)
        a = self.make_appt(doctor=d)
        r = MedicalRecord.objects.create(patient=p, doctor=d, diagnosis="x", prescription="y")
        resp = self.client.post(reverse("admin_delete_doctor", args=[d.id]))
        self.assertRedirectsTo(resp, "admin_doctors")
        self.assertFalse(Doctor.objects.filter(pk=d.pk).exists())
        for obj in (p, a, r):
            obj.refresh_from_db()
        self.assertIsNone(p.added_by)
        self.assertIsNone(a.doctor)
        self.assertIsNone(r.doctor)
        self.assertFlash(resp, "success", "Doctor deleted successfully")

    def test_delete_get_does_nothing(self):
        d = self.make_doctor()
        resp = self.client.get(reverse("admin_delete_doctor", args=[d.id]))
        self.assertRedirectsTo(resp, "admin_doctors")
        self.assertTrue(Doctor.objects.filter(pk=d.pk).exists())

    def test_delete_unknown_or_non_doctor_role(self):
        boss = self.make_doctor("boss", role="Admin")
        for pk in (99999, boss.id):
            with self.subTest(pk=pk):
                resp = self.client.post(reverse("admin_delete_doctor", args=[pk]))
                self.assertRedirectsTo(resp, "home")
        self.assertTrue(Doctor.objects.filter(pk=boss.pk).exists())


class AdminStaffTests(BaseTestCase):
    def setUp(self):
        self.login_admin()
        self.payload = {"name": "Sam", "role_title": "Receptionist", "phone": "9666666666", "email": "sam@clinic.com"}

    def test_list(self):
        s1, s2 = self.make_staff("A"), self.make_staff("B")
        resp = self.client.get(reverse("admin_staff"))
        self.assertTemplateUsed(resp, "admin/staff.html")
        self.assertCountEqual(resp.context["staff"], [s1, s2])

    def test_add_get_and_post(self):
        self.assertTemplateUsed(self.client.get(reverse("admin_add_staff")), "admin/add_staff.html")
        resp = self.client.post(reverse("admin_add_staff"), self.payload)
        self.assertRedirectsTo(resp, "admin_staff")
        s = Staff.objects.get()
        self.assertEqual((s.name, s.role_title, s.phone, s.email), ("Sam", "Receptionist", "9666666666", "sam@clinic.com"))
        self.assertFlash(resp, "success", "Staff member added successfully")

    def test_view(self):
        s = self.make_staff()
        resp = self.client.get(reverse("admin_view_staff", args=[s.id]))
        self.assertTemplateUsed(resp, "admin/view_staff.html")
        self.assertEqual(resp.context["staff_member"], s)

    def test_view_unknown(self):
        resp = self.client.get(reverse("admin_view_staff", args=[99999]))
        self.assertRedirectsTo(resp, "home")
        self.assertFlash(resp, "error", "Item not found")

    def test_edit(self):
        s = self.make_staff()
        self.assertTemplateUsed(self.client.get(reverse("admin_edit_staff", args=[s.id])), "admin/edit_staff.html")
        resp = self.client.post(reverse("admin_edit_staff", args=[s.id]), self.payload)
        self.assertRedirectsTo(resp, "admin_staff")
        s.refresh_from_db()
        self.assertEqual((s.name, s.role_title, s.phone, s.email), ("Sam", "Receptionist", "9666666666", "sam@clinic.com"))
        self.assertFlash(resp, "success", "Staff member updated successfully")

    def test_edit_unknown(self):
        self.assertRedirectsTo(self.client.get(reverse("admin_edit_staff", args=[99999])), "home")

    def test_delete_post(self):
        s = self.make_staff()
        resp = self.client.post(reverse("admin_delete_staff", args=[s.id]))
        self.assertRedirectsTo(resp, "admin_staff")
        self.assertFalse(Staff.objects.exists())
        self.assertFlash(resp, "success", "Staff member deleted successfully")

    def test_delete_get_does_nothing(self):
        s = self.make_staff()
        self.assertRedirectsTo(self.client.get(reverse("admin_delete_staff", args=[s.id])), "admin_staff")
        self.assertTrue(Staff.objects.exists())

    def test_delete_unknown(self):
        resp = self.client.post(reverse("admin_delete_staff", args=[99999]))
        self.assertRedirectsTo(resp, "home")
        self.assertFlash(resp, "error", "Item not found")


class AdminPatientTests(BaseTestCase):
    def setUp(self):
        self.login_admin()
        self.doc = self.make_doctor("drone")
        self.payload = {
            "name": "Pat", "age": "44", "gender": "Male", "phone": "9777777777",
            "address": "3 Lane", "doctor_id": self.doc.id,
        }

    # ---- list / search -----------------------------------------------------
    def test_list_all_patients(self):
        a, b = self.make_patient("A"), self.make_patient("B", self.doc)
        resp = self.client.get(reverse("admin_patients"))
        self.assertTemplateUsed(resp, "admin/patients.html")
        self.assertCountEqual(resp.context["patients"], [a, b])
        self.assertIsNone(resp.context["search_query"])

    def test_search_by_name_case_insensitive(self):
        self.make_patient("Alice")
        self.make_patient("Bob")
        resp = self.client.get(reverse("admin_patients"), {"q": "aLiC"})
        self.assertEqual([p.name for p in resp.context["patients"]], ["Alice"])
        self.assertEqual(resp.context["search_query"], "aLiC")

    def test_numeric_search_matches_patient_id(self):
        self.make_patient("Alice")
        bob = self.make_patient("Bob")
        resp = self.client.get(reverse("admin_patients"), {"q": str(bob.id)})
        self.assertEqual(list(resp.context["patients"]), [bob])

    def test_numeric_search_also_matches_names_containing_digits(self):
        p = self.make_patient("Room 101 Guest")
        self.make_patient("Other")
        resp = self.client.get(reverse("admin_patients"), {"q": "101"})
        self.assertIn(p, resp.context["patients"])

    def test_text_search_does_not_match_by_id(self):
        p = self.make_patient("Alice")
        resp = self.client.get(reverse("admin_patients"), {"q": f"{p.id}x"})
        self.assertEqual(len(resp.context["patients"]), 0)

    # ---- add ---------------------------------------------------------------
    def test_add_get_lists_doctors_only(self):
        self.make_doctor("boss", role="Admin")
        resp = self.client.get(reverse("admin_add_patient"))
        self.assertTemplateUsed(resp, "admin/add_patient.html")
        self.assertEqual(list(resp.context["doctors"]), [self.doc])

    def test_add_with_doctor(self):
        resp = self.client.post(reverse("admin_add_patient"), self.payload)
        self.assertRedirectsTo(resp, "admin_patients")
        p = Patient.objects.get()
        self.assertEqual((p.name, p.age, p.gender, p.phone, p.address), ("Pat", 44, "Male", "9777777777", "3 Lane"))
        self.assertEqual(p.added_by, self.doc)
        self.assertFlash(resp, "success", "Patient added successfully")

    def test_add_without_doctor_or_with_invalid_doctor(self):
        for doctor_id in ("", "99999"):
            with self.subTest(doctor_id=doctor_id):
                Patient.objects.all().delete()
                self.client.post(reverse("admin_add_patient"), {**self.payload, "doctor_id": doctor_id})
                self.assertIsNone(Patient.objects.get().added_by)

    def test_add_cannot_assign_non_doctor_role(self):
        boss = self.make_doctor("boss", role="Admin")
        self.client.post(reverse("admin_add_patient"), {**self.payload, "doctor_id": boss.id})
        self.assertIsNone(Patient.objects.get().added_by)

    # ---- view --------------------------------------------------------------
    def test_view(self):
        p = self.make_patient()
        resp = self.client.get(reverse("admin_view_patient", args=[p.id]))
        self.assertTemplateUsed(resp, "admin/view_patient.html")
        self.assertEqual(resp.context["patient"], p)

    def test_view_unknown(self):
        resp = self.client.get(reverse("admin_view_patient", args=[99999]))
        self.assertRedirectsTo(resp, "home")
        self.assertFlash(resp, "error", "Item not found")

    # ---- edit --------------------------------------------------------------
    def test_edit_get(self):
        p = self.make_patient()
        resp = self.client.get(reverse("admin_edit_patient", args=[p.id]))
        self.assertTemplateUsed(resp, "admin/edit_patient.html")
        self.assertEqual(list(resp.context["doctors"]), [self.doc])

    def test_edit_updates_and_reassigns_doctor(self):
        p = self.make_patient()
        resp = self.client.post(reverse("admin_edit_patient", args=[p.id]), {**self.payload, "name": "Edited"})
        self.assertRedirectsTo(resp, "admin_patients")
        p.refresh_from_db()
        self.assertEqual(p.name, "Edited")
        self.assertEqual(p.added_by, self.doc)
        self.assertFlash(resp, "success", "Patient updated successfully")

    def test_edit_blank_or_invalid_doctor_unassigns(self):
        for doctor_id in ("", "99999"):
            with self.subTest(doctor_id=doctor_id):
                p = self.make_patient("X", self.doc)
                self.client.post(reverse("admin_edit_patient", args=[p.id]), {**self.payload, "doctor_id": doctor_id})
                p.refresh_from_db()
                self.assertIsNone(p.added_by)

    def test_edit_unknown(self):
        self.assertRedirectsTo(self.client.get(reverse("admin_edit_patient", args=[99999])), "home")

    # ---- delete ------------------------------------------------------------
    def test_delete_post_cascades(self):
        p = self.make_patient("Gone", self.doc)
        MedicalRecord.objects.create(patient=p, diagnosis="d", prescription="p")
        Medisense.objects.create(patient=p, record_type="HR", value="70")
        resp = self.client.post(reverse("admin_delete_patient", args=[p.id]))
        self.assertRedirectsTo(resp, "admin_patients")
        self.assertFalse(Patient.objects.exists())
        self.assertFalse(MedicalRecord.objects.exists())
        self.assertFalse(Medisense.objects.exists())
        self.assertFlash(resp, "success", "Patient deleted successfully")

    def test_delete_get_does_nothing(self):
        p = self.make_patient()
        self.client.get(reverse("admin_delete_patient", args=[p.id]))
        self.assertTrue(Patient.objects.filter(pk=p.pk).exists())

    def test_delete_unknown(self):
        resp = self.client.post(reverse("admin_delete_patient", args=[99999]))
        self.assertRedirectsTo(resp, "home")
        self.assertFlash(resp, "error", "Item not found")


class AdminAppointmentTests(BaseTestCase):
    def setUp(self):
        self.login_admin()
        self.doc = self.make_doctor()

    def test_list_ordered_by_date_desc(self):
        old = self.make_appt(date=date(2030, 1, 1))
        new = self.make_appt(date=date(2030, 9, 1))
        resp = self.client.get(reverse("admin_appointments"))
        self.assertTemplateUsed(resp, "admin/appointments.html")
        self.assertEqual(list(resp.context["appointments"]), [new, old])

    def test_complete_with_doctor_creates_patient(self):
        a = self.make_appt(self.doc, "Pat Ient", age=33, gender="Female", address="A St", phone="9888888888")
        resp = self.client.post(reverse("admin_appointments"), {"appointment_id": a.id, "status": "Completed"})
        self.assertRedirectsTo(resp, "admin_appointments")
        a.refresh_from_db()
        self.assertEqual(a.status, "Completed")
        p = Patient.objects.get()
        self.assertEqual((p.name, p.phone, p.age, p.gender, p.address), ("Pat Ient", "9888888888", 33, "Female", "A St"))
        self.assertEqual(p.added_by, self.doc)
        self.assertFlash(resp, "success", "Appointment status updated")

    def test_complete_without_doctor_creates_no_patient_but_updates_status(self):
        a = self.make_appt(None)
        self.client.post(reverse("admin_appointments"), {"appointment_id": a.id, "status": "Completed"})
        a.refresh_from_db()
        self.assertEqual(a.status, "Completed")
        self.assertEqual(Patient.objects.count(), 0)

    def test_complete_does_not_duplicate_existing_patient(self):
        self.make_patient("Pat Ient", self.doc, phone="9000000003")
        a = self.make_appt(self.doc, "Pat Ient", phone="9000000003")
        self.client.post(reverse("admin_appointments"), {"appointment_id": a.id, "status": "Completed"})
        self.assertEqual(Patient.objects.count(), 1)

    def test_completing_twice_does_not_create_second_patient(self):
        a = self.make_appt(self.doc)
        payload = {"appointment_id": a.id, "status": "Completed"}
        self.client.post(reverse("admin_appointments"), payload)
        self.client.post(reverse("admin_appointments"), payload)
        self.assertEqual(Patient.objects.count(), 1)

    def test_other_status_changes(self):
        a = self.make_appt(self.doc)
        for status in ("Rejected", "Pending", "Completed"):
            with self.subTest(status=status):
                self.client.post(reverse("admin_appointments"), {"appointment_id": a.id, "status": status})
                a.refresh_from_db()
                self.assertEqual(a.status, status)

    def test_unknown_appointment(self):
        resp = self.client.post(reverse("admin_appointments"), {"appointment_id": 99999, "status": "Completed"})
        self.assertRedirectsTo(resp, "home")
        self.assertFlash(resp, "error", "Item not found")


# --------------------------------------------------------------------------- #
# END-TO-END WORKFLOW
# --------------------------------------------------------------------------- #
class FullClinicWorkflowTests(BaseTestCase):
    def test_signup_approve_book_claim_complete_record(self):
        doctor_client, admin_client, public_client = Client(), Client(), Client()

        # 1. Doctor signs up -> cannot log in yet
        doctor_client.post(reverse("signup"), {
            "username": "drflow", "email": "drflow@example.com", "password": STRONG_PASSWORD,
            "password_confirm": STRONG_PASSWORD, "specialization": "GP", "phone": "9876500000",
        })
        doc = Doctor.objects.get(username="drflow")
        creds = {"username": "drflow", "password": STRONG_PASSWORD}
        doctor_client.post(reverse("login"), creds)
        self.assertNotIn("doctor_id", doctor_client.session)

        # 2. Admin logs in and approves
        admin_client.post(reverse("admin_login"), {"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
        admin_client.post(reverse("admin_approve_doctor", args=[doc.id]))
        doc.refresh_from_db()
        self.assertTrue(doc.is_approved)

        # 3. Doctor now logs in
        resp = doctor_client.post(reverse("login"), creds)
        self.assertRedirectsTo(resp, "doctor_dashboard")

        # 4. Public visitor books an unassigned appointment
        public_client.post(reverse("book_appointment"), {
            "patient_name": "Flow Patient", "age": "29", "gender": "Female", "address": "Flow St",
            "phone": "9123456789", "date": "2030-07-01", "time": "11:00", "reason": "Cough",
        })
        appt = Appointment.objects.get()
        dash = doctor_client.get(reverse("doctor_dashboard"))
        self.assertIn(appt, dash.context["unassigned_appointments"])

        # 5. Doctor claims and completes it
        doctor_client.post(reverse("doctor_accept_appointment", args=[appt.id]))
        doctor_client.post(reverse("doctor_complete_appointment", args=[appt.id]))
        appt.refresh_from_db()
        self.assertEqual(appt.doctor, doc)
        self.assertEqual(appt.status, "Completed")
        patient = Patient.objects.get(name="Flow Patient")
        self.assertEqual(patient.added_by, doc)

        # 6. Doctor adds a medical record
        doctor_client.post(
            reverse("doctor_medical_records", args=[patient.id]),
            {"diagnosis": "Bronchitis", "prescription": "Antibiotics"},
        )
        self.assertEqual(patient.medical_records.get().doctor, doc)

        # 7. Admin dashboard reflects everything
        ctx = admin_client.get(reverse("admin_dashboard")).context
        self.assertEqual((ctx["doctor_count"], ctx["patient_count"], ctx["appointment_count"]), (1, 1, 1))

        # 8. Admin deletes patient -> records cascade
        admin_client.post(reverse("admin_delete_patient", args=[patient.id]))
        self.assertEqual(MedicalRecord.objects.count(), 0)


# --------------------------------------------------------------------------- #
# KNOWN ISSUES
# Each test asserts the *desired* behaviour and is marked @expectedFailure
# because views.py does not do it today. When you fix the bug the test turns
# into an "unexpected success" - just delete the decorator.
# --------------------------------------------------------------------------- #
class KnownIssueTests(BaseTestCase):
    def setUp(self):
        self.doc = self.make_doctor("drone")
        self.other = self.make_doctor("drtwo")

    @expectedFailure
    def test_doctor_cannot_read_or_write_records_of_another_doctors_patient(self):
        """doctor_medical_records looks the patient up by id only (IDOR)."""
        theirs = self.make_patient("Theirs", self.other)
        self.login_doctor(self.doc)
        resp = self.client.get(reverse("doctor_medical_records", args=[theirs.id]))
        self.assertEqual(resp.status_code, 302)

    @expectedFailure
    def test_unapproved_doctor_cannot_be_assigned_via_public_booking(self):
        """book_appointment only checks role, not is_approved."""
        pending = self.make_doctor("pending", approved=False)
        self.client.post(reverse("book_appointment"), {
            "patient_name": "X", "age": "1", "gender": "Male", "address": "a", "phone": "1",
            "date": "2030-01-01", "time": "10:00", "reason": "r", "doctor": pending.id,
        })
        self.assertIsNone(Appointment.objects.get().doctor)

    @expectedFailure
    def test_booking_with_non_numeric_age_should_not_crash(self):
        """No validation: int('abc') raises ValueError -> HTTP 500."""
        resp = self.client.post(reverse("book_appointment"), {
            "patient_name": "X", "age": "abc", "gender": "Male", "address": "a", "phone": "1",
            "date": "2030-01-01", "time": "10:00", "reason": "r",
        })
        self.assertIn(resp.status_code, (200, 302))

    @expectedFailure
    def test_approval_toggle_should_not_happen_on_get(self):
        """State change on GET (CSRF-able)."""
        self.login_admin()
        d = self.make_doctor("pending", approved=False)
        self.client.get(reverse("admin_approve_doctor", args=[d.id]))
        d.refresh_from_db()
        self.assertFalse(d.is_approved)

    @expectedFailure
    def test_revoking_approval_should_end_active_doctor_session(self):
        """get_current_doctor never checks is_approved after login."""
        self.login_doctor(self.doc)
        Doctor.objects.filter(pk=self.doc.pk).update(is_approved=False)
        resp = self.client.get(reverse("doctor_dashboard"))
        self.assertEqual(resp.status_code, 302)

    @expectedFailure
    def test_rejected_appointment_should_not_be_completable(self):
        self.login_doctor(self.doc)
        appt = self.make_appt(self.doc, status="Rejected")
        self.client.post(reverse("doctor_complete_appointment", args=[appt.id]))
        appt.refresh_from_db()
        self.assertEqual(appt.status, "Rejected")

    @expectedFailure
    def test_admin_should_not_set_arbitrary_appointment_status(self):
        self.login_admin()
        appt = self.make_appt(self.doc)
        self.client.post(reverse("admin_appointments"), {"appointment_id": appt.id, "status": "Bogus"})
        appt.refresh_from_db()
        self.assertEqual(appt.status, "Pending")

    @expectedFailure
    def test_admin_add_doctor_with_duplicate_username_should_show_error_not_crash(self):
        """No uniqueness check -> IntegrityError (HTTP 500)."""
        self.login_admin()
        resp = self.client.post(reverse("admin_add_doctor"), {
            "username": "drone", "email": "fresh@example.com", "password": STRONG_PASSWORD,
            "specialization": "x", "phone": "9876543210",
        })
        self.assertIn(resp.status_code, (200, 302))

    @expectedFailure
    def test_admin_edit_doctor_with_duplicate_email_should_show_error_not_crash(self):
        self.login_admin()
        resp = self.client.post(reverse("admin_edit_doctor", args=[self.doc.id]), {
            "username": "drone", "email": self.other.email, "phone": "9876543210",
            "specialization": "x", "password": "",
        })
        self.assertIn(resp.status_code, (200, 302))
