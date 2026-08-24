from django.urls import path
from . import views

urlpatterns = [
    # Public
    path('', views.home, name='home'),
    path('book-appointment/', views.book_appointment, name='book_appointment'),
    
    # Auth
    path('login/', views.doctor_login, name='login'),
    path('signup/', views.doctor_signup, name='signup'),
    path('logout/', views.doctor_logout, name='logout'),
    
    # Admin Auth
    path('management/login/', views.admin_login, name='admin_login'),
    path('management/logout/', views.admin_logout, name='admin_logout'),
    
    # Doctor Views
    path('doctors/', views.doctor_dashboard, name='doctor_dashboard'),
    path('doctors/patients/', views.doctor_patients, name='doctor_patients'),
    path('doctors/patients/add/', views.doctor_add_patient, name='doctor_add_patient'),
    path('doctors/patients/<int:patient_id>/edit/', views.doctor_edit_patient, name='doctor_edit_patient'),
    path('doctors/patients/<int:patient_id>/records/', views.doctor_medical_records, name='doctor_medical_records'),
    path('doctors/appointments/<int:appointment_id>/accept/', views.doctor_accept_appointment, name='doctor_accept_appointment'),
    path('doctors/appointments/<int:appointment_id>/complete/', views.doctor_complete_appointment, name='doctor_complete_appointment'),
    path('doctors/appointments/<int:appointment_id>/reject/', views.doctor_reject_appointment, name='doctor_reject_appointment'),
    
    # Admin Views
    path('management/', views.admin_dashboard, name='admin_dashboard'),
    path('management/doctors/', views.admin_doctors, name='admin_doctors'),
    path('management/doctors/add/', views.admin_add_doctor, name='admin_add_doctor'),
    path('management/doctors/<int:doctor_id>/', views.admin_view_doctor, name='admin_view_doctor'),
    path('management/doctors/<int:doctor_id>/edit/', views.admin_edit_doctor, name='admin_edit_doctor'),
    path('management/doctors/<int:doctor_id>/delete/', views.admin_delete_doctor, name='admin_delete_doctor'),
    path('management/doctors/<int:doctor_id>/approve/', views.admin_approve_doctor, name='admin_approve_doctor'),
    path('management/staff/', views.admin_staff, name='admin_staff'),
    path('management/staff/add/', views.admin_add_staff, name='admin_add_staff'),
    path('management/staff/<int:staff_id>/', views.admin_view_staff, name='admin_view_staff'),
    path('management/staff/<int:staff_id>/edit/', views.admin_edit_staff, name='admin_edit_staff'),
    path('management/staff/<int:staff_id>/delete/', views.admin_delete_staff, name='admin_delete_staff'),
    path('management/patients/', views.admin_patients, name='admin_patients'),
    path('management/patients/add/', views.admin_add_patient, name='admin_add_patient'),
    path('management/patients/<int:patient_id>/', views.admin_view_patient, name='admin_view_patient'),
    path('management/patients/<int:patient_id>/edit/', views.admin_edit_patient, name='admin_edit_patient'),
    path('management/patients/<int:patient_id>/delete/', views.admin_delete_patient, name='admin_delete_patient'),
    path('management/appointments/', views.admin_appointments, name='admin_appointments'),
]
