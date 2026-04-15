from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from datetime import date, timedelta, datetime
from django.utils import timezone
from django.db.models import Count, Q
from django.db import models
import json
from .models import Book, Category, BorrowRecord, UserProfile, Computer, MeetingRoomSchedule, EnrolledStudent, Meeting
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.http import HttpResponse
from django.conf import settings  
from django.contrib.auth import update_session_auth_hash
from django.http import JsonResponse
import random
from django.urls import reverse
import openpyxl
from django.contrib import messages
from .models import Notification

def user_login(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            return redirect('dashboard')
    else:
        form = AuthenticationForm()
    return render(request, 'catalog/login.html', {'form': form})

def user_logout(request):
    logout(request)
    return redirect('login')

@login_required
def dashboard(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    context = {'profile': profile, 'active_tab': 'dashboard'}
    
    # 1. ADMIN (LIBRARIAN) DASHBOARD
    if profile.role == 'admin':
        context['pending_requests'] = BorrowRecord.objects.filter(is_returned=False, book__status='Pending').order_by('borrow_date')
        
        active_q = request.GET.get('active_q', '')
        active_borrows = BorrowRecord.objects.filter(is_returned=False, book__status='Borrowed').order_by('-borrow_date')
        if active_q:
            active_borrows = active_borrows.filter(Q(book__title__icontains=active_q) | Q(book__book_id__icontains=active_q) | Q(user__username__icontains=active_q) | Q(user__userprofile__id_number__icontains=active_q))
        context['active_borrows'] = active_borrows
        context['active_q'] = active_q
        
        cat_data = BorrowRecord.objects.values('book__category__name').annotate(count=Count('id'))
        context['cat_names'] = json.dumps([d['book__category__name'] or 'Uncategorized' for d in cat_data])
        context['cat_counts'] = json.dumps([d['count'] for d in cat_data])
        return render(request, 'catalog/admin_dashboard.html', context)

    # 2. INSTRUCTOR DASHBOARD
    elif profile.role == 'instructor':
        context['is_instructor'] = True 
        context['computers'] = Computer.objects.all().order_by('name')
        context['my_borrows'] = BorrowRecord.objects.filter(user=request.user, is_returned=False)
        context['my_history_borrows'] = BorrowRecord.objects.filter(user=request.user, is_returned=True).order_by('-return_date')
        context['my_meetings'] = MeetingRoomSchedule.objects.filter(user=request.user, status='Upcoming').order_by('date')
        context['my_history_meetings'] = MeetingRoomSchedule.objects.filter(user=request.user, status='Completed').order_by('-date')
        
        last_borrow = BorrowRecord.objects.filter(user=request.user).order_by('-borrow_date').first()
        recommended_books = None
        if last_borrow and last_borrow.book.category:
            recommended_books = Book.objects.filter(category=last_borrow.book.category, status='Available').exclude(id=last_borrow.book.id).order_by('?')[:3]
        if not recommended_books or not recommended_books.exists():
            recommended_books = Book.objects.filter(status='Available').order_by('-id')[:3]
        context['recommended_books'] = recommended_books
        return render(request, 'catalog/user_dashboard.html', context)

    # 3. STUDENT DASHBOARD
    else:
        context['computers'] = Computer.objects.all().order_by('name')
        context['my_borrows'] = BorrowRecord.objects.filter(user=request.user, is_returned=False)
        context['my_history_borrows'] = BorrowRecord.objects.filter(user=request.user, is_returned=True).order_by('-return_date')
        context['my_meetings'] = MeetingRoomSchedule.objects.filter(user=request.user, status='Upcoming').order_by('date')
        context['my_history_meetings'] = MeetingRoomSchedule.objects.filter(user=request.user, status='Completed').order_by('-date')
        
        last_borrow = BorrowRecord.objects.filter(user=request.user).order_by('-borrow_date').first()
        recommended_books = None
        if last_borrow and last_borrow.book.category:
            recommended_books = Book.objects.filter(category=last_borrow.book.category, status='Available').exclude(id=last_borrow.book.id).order_by('?')[:3]
        if not recommended_books or not recommended_books.exists():
            recommended_books = Book.objects.filter(status='Available').order_by('-id')[:3]
        context['recommended_books'] = recommended_books
        return render(request, 'catalog/user_dashboard.html', context)

@login_required
def admin_pcs(request):
    if request.user.userprofile.role != 'admin': return redirect('dashboard')
    context = {'profile': request.user.userprofile, 'active_tab': 'pcs', 'computers': Computer.objects.all().order_by('name'), 'all_students': User.objects.filter(userprofile__role__in=['student', 'instructor'])}
    return render(request, 'catalog/admin_pcs.html', context)

@login_required
def admin_history(request):
    if request.user.userprofile.role != 'admin': return redirect('dashboard')
    context = {'profile': request.user.userprofile, 'active_tab': 'history', 'history_borrows': BorrowRecord.objects.filter(is_returned=True).order_by('-return_date'), 'history_meetings': MeetingRoomSchedule.objects.filter(status='Completed').order_by('-date')}
    return render(request, 'catalog/admin_history.html', context)

@login_required
def admin_management(request):
    if request.user.userprofile.role != 'admin': return redirect('dashboard')
    
    inventory_q = request.GET.get('inventory_q', '')
    books = Book.objects.all().order_by('book_id')
    if inventory_q: 
        books = books.filter(Q(title__icontains=inventory_q) | Q(book_id__icontains=inventory_q))

    student_q = request.GET.get('student_q', '')
    dept_filter = request.GET.get('department', '')
    sec_filter = request.GET.get('section', '')
    
    all_users = User.objects.filter(userprofile__role__in=['student', 'instructor']).order_by('username')
    
    if student_q:
        all_users = all_users.filter(
            Q(username__icontains=student_q) | 
            Q(first_name__icontains=student_q) | 
            Q(last_name__icontains=student_q) | 
            Q(userprofile__id_number__icontains=student_q)
        )

    context = {
        'profile': request.user.userprofile, 
        'active_tab': 'management', 
        'categories': Category.objects.all(), 
        'books': books, 
        'total_books': Book.objects.count(), 
        'available_books': Book.objects.filter(status='Available').count(), 
        'unavailable_books': Book.objects.exclude(status='Available').count(), 
        'inventory_q': inventory_q, 
        'all_users': all_users,
        'departments': [], 
        'sections': [],    
    }
    return render(request, 'catalog/admin_management.html', context)

@login_required
def browse_library(request):
    profile = request.user.userprofile
    books = Book.objects.all().order_by('category__name', 'title')
    categories = Category.objects.all()
    search_query = request.GET.get('q', '')
    cat_query = request.GET.get('category', '')
    if search_query: books = books.filter(title__icontains=search_query) | books.filter(author__icontains=search_query) | books.filter(book_id__icontains=search_query)
    if cat_query: books = books.filter(category__id=cat_query)
    return render(request, 'catalog/browse_library.html', {'books': books, 'profile': profile, 'categories': categories, 'search_query': search_query, 'cat_query': cat_query, 'active_tab': 'browse'})

@login_required
def edit_profile(request):
    user = request.user
    profile = user.userprofile
    
    if request.method == 'POST':
        user.first_name = request.POST.get('first_name', user.first_name).strip()
        user.last_name = request.POST.get('last_name', user.last_name).strip()
        
        new_email = request.POST.get('email', '').strip()
        if new_email:
            user.email = new_email
        
        user.save()

        profile.id_number = request.POST.get('id_number', profile.id_number).strip()
        
        if 'profile_photo' in request.FILES:
            profile.profile_photo = request.FILES['profile_photo']
            
        profile.save()
        return redirect('edit_profile')

    context = {
        'user': user,
        'profile': profile,
        'active_tab': 'profile'
    }
    return render(request, 'catalog/edit_profile.html', context)

@login_required
def borrow_book(request, book_id):
    book = get_object_or_404(Book, id=book_id)
    if book.status == 'Available':
        book.status = 'Pending'
        book.save()
        BorrowRecord.objects.create(book=book, user=request.user, due_date=date.today() + timedelta(days=7))
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))

@login_required
def approve_borrow(request, record_id):
    if request.user.userprofile.role == 'admin':
        record = get_object_or_404(BorrowRecord, id=record_id)
        record.book.status = 'Borrowed'
        record.book.save()
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))

@login_required
def reject_borrow(request, record_id):
    if request.user.userprofile.role == 'admin':
        record = get_object_or_404(BorrowRecord, id=record_id)
        record.book.status = 'Available'
        record.book.save()
        record.delete()
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))

@login_required
def return_book(request, record_id):
    if request.user.userprofile.role == 'admin':
        record = get_object_or_404(BorrowRecord, id=record_id)
        record.final_penalty = record.penalty_fee
        record.is_returned = True
        record.return_date = date.today()
        record.save()
        record.book.status = 'Available'
        record.book.save()
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))

@login_required
def edit_due_date(request, record_id):
    if request.method == 'POST' and request.user.userprofile.role == 'admin':
        record = get_object_or_404(BorrowRecord, id=record_id)
        new_date = request.POST.get('due_date')
        if new_date:
            record.due_date = new_date
            record.save()
            student_email = record.user.userprofile.email
            if student_email:
                subject = f"Library Notice: Due Date Changed for '{record.book.title}'"
                message = f"Hello {record.user.username},\n\nThe librarian has updated the due date for your borrowed book '{record.book.title}'.\n\nYour new due date is: {new_date}.\n\nPlease ensure the book is returned on or before this date to avoid penalties.\n\nThank you,\nCEC Library System"
                try:
                    send_mail(subject, message, settings.EMAIL_HOST_USER, [student_email], fail_silently=False)
                except Exception as e:
                    print(f"Email failed to send: {e}")
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))

@login_required
def book_room(request):
    if request.method == 'POST': MeetingRoomSchedule.objects.create(user=request.user, date=request.POST.get('date'), time_slot=request.POST.get('time_slot'), purpose=request.POST.get('purpose'))
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))

@login_required
def complete_meeting(request, meeting_id):
    if request.user.userprofile.role == 'admin':
        meeting = get_object_or_404(MeetingRoomSchedule, id=meeting_id)
        meeting.status = 'Completed'
        meeting.save()
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))

@login_required
def request_pc(request, pc_id):
    if request.user.userprofile.role != 'admin':
        pc = get_object_or_404(Computer, id=pc_id)
        if pc.status == 'Available':
            pc.status = 'Requested'
            pc.current_user = request.user
            pc.save()
            
            
            admins = User.objects.filter(userprofile__role='admin')
            for admin in admins:
                Notification.objects.create(
                    recipient=admin,
                    message=f"New PC request from {request.user.first_name} for {pc.name}.",
                    target_url=reverse('admin_pcs')
                )
                
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))

@login_required
def approve_pc(request, pc_id):
    if request.user.userprofile.role == 'admin':
        pc = get_object_or_404(Computer, id=pc_id)
        if pc.status == 'Requested':
            pc.status = 'In Use'
            pc.time_started = timezone.now()
            
          
            student_to_notify = pc.current_user 
            pc.save()
            
            
            if student_to_notify:
                Notification.objects.create(
                    recipient=student_to_notify,
                    message=f"Your request for {pc.name} has been APPROVED.",
                    target_url=reverse('dashboard')
                )
                
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))

@login_required
def reject_pc(request, pc_id):
    if request.user.userprofile.role == 'admin':
        pc = get_object_or_404(Computer, id=pc_id)
        
        student_to_notify = pc.current_user 
        
        pc.status = 'Available'
        pc.current_user = None
        pc.save()
        
      
        if student_to_notify:
            Notification.objects.create(
                recipient=student_to_notify,
                message=f"Your request for {pc.name} has been REJECTED.",
                target_url=reverse('dashboard')
            )
            
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))

@login_required
def stop_pc(request, pc_id):
    if request.user.userprofile.role == 'admin':
        pc = get_object_or_404(Computer, id=pc_id)
        
        student_to_notify = pc.current_user 
        
        pc.status = 'Available'
        pc.current_user = None
        pc.time_started = None
        pc.save()
        
       
        if student_to_notify:
            Notification.objects.create(
                recipient=student_to_notify,
                message=f"Your session on {pc.name} has been ended by the Admin.",
                target_url=reverse('dashboard')
            )
            
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))

@login_required
def add_user(request):
    if request.method == 'POST' and request.user.userprofile.role == 'admin':
        username = request.POST.get('username')
        if not User.objects.filter(username=username).exists():
            user = User.objects.create_user(username=username, password=request.POST.get('password'))
            UserProfile.objects.create(user=user, role=request.POST.get('role'), id_number=request.POST.get('id_number'), email=request.POST.get('email'))
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))

@login_required
def add_book(request):
    if request.method == 'POST' and request.user.userprofile.role == 'admin':
        if not Book.objects.filter(book_id=request.POST.get('book_id')).exists():
            cat = Category.objects.get(id=request.POST.get('category_id')) if request.POST.get('category_id') else None
            Book.objects.create(book_id=request.POST.get('book_id'), title=request.POST.get('title'), author=request.POST.get('author'), category=cat)
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))

@login_required
def toggle_book_status(request, book_id):
    if request.user.userprofile.role == 'admin':
        book = get_object_or_404(Book, id=book_id)
        book.status = 'Unavailable' if book.status == 'Available' else 'Available'
        book.save()
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))

@login_required
def reset_password(request):
    if request.method == 'POST' and request.user.userprofile.role == 'admin':
        user_to_reset = get_object_or_404(User, id=request.POST.get('user_id'))
        user_to_reset.set_password(request.POST.get('new_password'))
        user_to_reset.save()
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))

def send_daily_reminders(request):
    # 1. Use timezone to match Render's clock perfectly
    tomorrow = timezone.now().date() + timedelta(days=1)
    
    # 2. ADDED __date HERE to ignore hours and minutes!
    due_tomorrow_records = BorrowRecord.objects.filter(is_returned=False, due_date=tomorrow)
    
    emails_sent = 0
    for record in due_tomorrow_records:
        student_email = record.user.userprofile.email
        if student_email:
            subject = f"Library Reminder: '{record.book.title}' is due tomorrow!"
            
            # Using record.user.first_name if they have one, otherwise username
            name_to_use = record.user.first_name if record.user.first_name else record.user.username
            
            message = f"""Hello {name_to_use},

This is an automated reminder from the Library System.

Your borrowed book '{record.book.title}' is due tomorrow ({tomorrow.strftime('%b %d, %Y')}).
Please return it on time to avoid a penalty fee of ₱5.00 per day.

Thank you!
CEC Library System"""
            
            try:
                send_mail(subject, message, settings.EMAIL_HOST_USER, [student_email], fail_silently=False)
                emails_sent += 1
            except Exception as e:
                print(f"Error sending to {student_email}: {e}")

    return HttpResponse(f"System Check Complete. Sent {emails_sent} reminder emails for books due on {tomorrow} using {settings.EMAIL_HOST_USER}.")

@login_required
def digital_id(request):
    profile = request.user.userprofile

    # Admin Security Gate: Keep admins out of the Digital ID page
    if profile.role == 'admin':
        return redirect('dashboard')
    
    clean_id = profile.id_number.strip() if profile.id_number else ""
    
    try:
        student_record = EnrolledStudent.objects.get(id_number=clean_id)
        current_status = student_record.enrollment_status
    except EnrolledStudent.DoesNotExist:
        current_status = "Unknown"

    today = timezone.now()
    next_year_date = today + timedelta(days=365) 
    valid_until = next_year_date.strftime("%B %Y").upper() 
    
    # Pass the clean_id to the QR code so the link works perfectly
    qr_url = request.build_absolute_uri(reverse('verify_student', args=[clean_id]))

    context = {
        'profile': profile,
        'active_tab': 'digital_id',
        'status': current_status,
        'valid_until': valid_until, 
        'qr_url': qr_url,
    }
    return render(request, 'catalog/digital_id.html', context)

@login_required
def admin_user_logs(request):
    if request.user.userprofile.role != 'admin':
        return redirect('dashboard')
    
    query = request.GET.get('q', '')
    
    users = User.objects.exclude(userprofile__role='admin').order_by('username')
    
    if query:
        users = users.filter(
            Q(username__icontains=query) | 
            Q(first_name__icontains=query) | 
            Q(last_name__icontains=query) | 
            Q(userprofile__id_number__icontains=query)
        )
    
    user_logs = []
    for u in users:
        last_borrow = BorrowRecord.objects.filter(user=u).order_by('-borrow_date').first()
        user_logs.append({
            'user': u,
            'profile': u.userprofile,
            'last_borrow': last_borrow
        })
        
    context = {
        'profile': request.user.userprofile,
        'active_tab': 'user_logs',
        'user_logs': user_logs,
        'query': query
    }
    return render(request, 'catalog/admin_user_logs.html', context)

@login_required
def activate_student(request, student_id):
    if request.user.userprofile.role == 'admin':
        student = get_object_or_404(EnrolledStudent, id=student_id)
        
        if not student.is_activated:
            base_username = f"{student.first_name.strip()}.{student.last_name.strip()}".replace(" ", "").lower()
            
            username = base_username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1

            user = User.objects.create_user(
                username=username,           
                password=student.id_number,  
                first_name=student.first_name,
                last_name=student.last_name
            )
            
            UserProfile.objects.create(
                user=user,
                role='student',
                id_number=student.id_number
            )
            
            student.is_activated = True
            student.save()
            
    return redirect(request.META.get('HTTP_REFERER', 'admin_masterlist'))

@login_required
def change_password(request):
    if request.method == 'POST':
        new_pass = request.POST.get('new_password')
        confirm_pass = request.POST.get('confirm_password')
        
        if new_pass and new_pass == confirm_pass:
            request.user.set_password(new_pass)
            request.user.save()
            update_session_auth_hash(request, request.user) 
            
    return redirect(request.META.get('HTTP_REFERER', 'edit_profile'))

@login_required
def admin_masterlist(request):
    if request.user.userprofile.role != 'admin': return redirect('dashboard')
    
    departments = ['BSIT', 'BSCRIM', 'BSHM', 'BSTM', 'BSED-English', 'BSED-Math', 'BEED']
    selected_dept = request.GET.get('department', 'BSIT')
    search_q = request.GET.get('q', '')
    
    masterlist = EnrolledStudent.objects.filter(department=selected_dept).order_by('last_name')
    
    if search_q:
        terms = search_q.split()
        for term in terms:
            masterlist = masterlist.filter(
                Q(first_name__icontains=term) | 
                Q(last_name__icontains=term) | 
                Q(id_number__icontains=term)
            )

    context = {
        'profile': request.user.userprofile,
        'active_tab': 'masterlist',
        'departments': departments,
        'selected_dept': selected_dept,
        'masterlist': masterlist,
        'search_q': search_q
    }
    return render(request, 'catalog/admin_masterlist.html', context)


@login_required
def update_student_status(request, student_id):
    if request.user.userprofile.role != 'admin': return redirect('dashboard')
    
    if request.method == 'POST':
        student = get_object_or_404(EnrolledStudent, id=student_id)
        new_status = request.POST.get('status')
        
        student.enrollment_status = new_status
        student.save()

        if student.is_activated:
            try:
                profile = UserProfile.objects.get(id_number=student.id_number)
                user = profile.user
                if new_status == 'Enrolled':
                    user.is_active = True
                else:
                    user.is_active = False 
                user.save()
            except UserProfile.DoesNotExist:
                pass
                
    return redirect(request.META.get('HTTP_REFERER', 'admin_masterlist'))

@login_required
def bulk_sync_students(request):
    if request.user.userprofile.role != 'admin': return redirect('dashboard')
    
    if request.method == 'POST' and request.FILES.get('excel_file'):
        excel_file = request.FILES['excel_file']
        
        if not (excel_file.name.endswith('.xlsx') or excel_file.name.endswith('.xls')):
            return redirect('admin_masterlist')
            
        try:
            wb = openpyxl.load_workbook(excel_file, data_only=True)
            sheet = wb.active
            
            headers = [str(cell.value).strip().lower() if cell.value else '' for cell in sheet[1]]
            
            id_idx = headers.index('id_number')
            fname_idx = headers.index('first_name')
            lname_idx = headers.index('last_name')
            dept_idx = headers.index('department')
            year_idx = headers.index('enrollment_year')
            
            officially_enrolled_ids = set()
            
            for row in sheet.iter_rows(min_row=2, values_only=True):
                raw_id = row[id_idx]
                if isinstance(raw_id, float):
                    student_id = str(int(raw_id)) 
                else:
                    student_id = str(raw_id).strip() if raw_id else ''
                
                if not student_id or student_id == 'None': continue
                
                officially_enrolled_ids.add(student_id)
                
                first_name = str(row[fname_idx]).strip() if row[fname_idx] else 'Unknown'
                last_name = str(row[lname_idx]).strip() if row[lname_idx] else 'Unknown'
                department = str(row[dept_idx]).strip() if row[dept_idx] else 'Unknown'
                
                try:
                    enroll_year = int(row[year_idx])
                except (ValueError, TypeError):
                    enroll_year = date.today().year
                
                student, created = EnrolledStudent.objects.get_or_create(
                    id_number=student_id,
                    defaults={
                        'first_name': first_name,
                        'last_name': last_name,
                        'department': department,
                        'enrollment_year': enroll_year,
                        'enrollment_status': 'Enrolled'
                    }
                )
                
                if not created:
                    student.enrollment_status = 'Enrolled'
                    student.department = department 
                    student.enrollment_year = enroll_year
                    student.save()
                    
                if student.is_activated:
                    try:
                        profile = UserProfile.objects.get(id_number=student.id_number)
                        profile.user.is_active = True
                        profile.user.save()
                    except UserProfile.DoesNotExist:
                        pass

            missing_students = EnrolledStudent.objects.exclude(id_number__in=officially_enrolled_ids)
            for s in missing_students:
                s.enrollment_status = 'Dropped'
                s.save()
                if s.is_activated:
                    try:
                        p = UserProfile.objects.get(id_number=s.id_number)
                        p.user.is_active = False 
                        p.user.save()
                    except UserProfile.DoesNotExist:
                        pass
                        
        except Exception as e:
            print("--- BULK SYNC ERROR ---")
            print(str(e))
            print("-----------------------")
            
    return redirect(request.META.get('HTTP_REFERER', 'admin_masterlist'))

@login_required
def admin_meetings(request):
    if request.user.userprofile.role != 'admin': return redirect('dashboard')
    
    all_meetings = Meeting.objects.all().order_by(
        models.Case(
            models.When(status='Pending', then=0),
            default=1
        ),
        '-created_at'
    )
    
    context = {
        'profile': request.user.userprofile,
        'active_tab': 'meetings',
        'meetings': all_meetings
    }
    return render(request, 'catalog/admin_meetings.html', context)

@login_required
def update_meeting_status(request, meeting_id):
    if request.user.userprofile.role != 'admin': return redirect('dashboard')
    
    if request.method == 'POST':
        meeting = get_object_or_404(Meeting, id=meeting_id)
        action = request.POST.get('action') 
        
        if action == 'Approve':
            conflicts = Meeting.objects.filter(
                meeting_date=meeting.meeting_date,
                status='Approved',
                start_time__lt=meeting.end_time,
                end_time__gt=meeting.start_time
            ).exclude(id=meeting.id)
            
            if conflicts.exists():
                messages.error(request, "Cannot approve. This overlaps with an already approved meeting.")
            else:
                meeting.status = 'Approved'
                meeting.save()
                messages.success(request, "Meeting Approved.")
                
                Notification.objects.create(
                    recipient=meeting.student,
                    message=f"Your room request for {meeting.meeting_date} has been APPROVED.",
                    target_url=reverse('student_meetings') + f"#meeting-{meeting.id}"
                )
                
                Meeting.objects.filter(
                    meeting_date=meeting.meeting_date,
                    status='Pending',
                    start_time__lt=meeting.end_time,
                    end_time__gt=meeting.start_time
                ).update(status='Rejected')
                
        elif action == 'Reject':
            meeting.status = 'Rejected'
            meeting.save()
            messages.success(request, "Meeting Rejected.")
            
            Notification.objects.create(
                recipient=meeting.student,
                message=f"Your room request for {meeting.meeting_date} has been REJECTED.",
                target_url=reverse('student_meetings') + f"#meeting-{meeting.id}"
            )
            
    return redirect('admin_meetings')

@login_required
def student_meetings(request):
    if request.user.userprofile.role == 'admin': return redirect('admin_meetings')
        
    today = timezone.now().date() 

    if request.method == 'POST':
        date_str = request.POST.get('meeting_date')
        start = request.POST.get('start_time')
        end = request.POST.get('end_time')
        purpose = request.POST.get('purpose')
        
        submitted_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        if submitted_date < today:
            messages.error(request, "Invalid Date: You cannot book a meeting in the past.")
            return redirect('student_meetings')
            
        conflicts = Meeting.objects.filter(
            meeting_date=date_str,
            status='Approved',
            start_time__lt=end, 
            end_time__gt=start  
        )
        
        if conflicts.exists():
            messages.error(request, "This time slot is already booked by someone else.")
        else:
            new_meeting = Meeting.objects.create(
                student=request.user,
                meeting_date=date_str,
                start_time=start,
                end_time=end,
                purpose=purpose,
                status='Pending'
            )
            
            admins = User.objects.filter(userprofile__role='admin')
            for admin in admins:
                Notification.objects.create(
                    recipient=admin,
                    message=f"New room request from {request.user.first_name} for {date_str}.",
                    target_url=reverse('admin_meetings') + f"#meeting-{new_meeting.id}"
                )
            
            messages.success(request, "Meeting request submitted! Waiting for admin approval.")
            
        return redirect('student_meetings')

    my_appointments = Meeting.objects.filter(student=request.user).order_by('-meeting_date', '-start_time')

    booked_slots = Meeting.objects.filter(
        status='Approved', 
        meeting_date__gte=today
    ).order_by('meeting_date', 'start_time')

    context = {
        'profile': request.user.userprofile,
        'active_tab': 'meetings',
        'appointments': my_appointments,
        'booked_slots': booked_slots,
        'today_string': today.strftime('%Y-%m-%d') 
    }
    return render(request, 'catalog/student_meetings.html', context)


def verify_student(request, id_number):
    try:
        student = EnrolledStudent.objects.get(id_number=id_number)
        status = student.enrollment_status
        
        try:
            profile = UserProfile.objects.get(id_number=id_number)
        except UserProfile.DoesNotExist:
            profile = None
            
    except EnrolledStudent.DoesNotExist:
        student = None
        status = "Invalid"
        profile = None

    context = {
        'student': student,
        'status': status,
        'profile': profile,
        'scanned_id': id_number
    }
    return render(request, 'catalog/verify_student.html', context)

@login_required
def get_notifications(request):
    unread = Notification.objects.filter(recipient=request.user, is_read=False)[:5]
    
    data = []
    for notif in unread:
        data.append({
            'id': notif.id,
            'message': notif.message,
            'time': notif.created_at.strftime("%I:%M %p"),
            'url': reverse('read_notification', args=[notif.id]) 
        })

    return JsonResponse({
        'count': unread.count(),
        'alerts': data
    })

@login_required
def read_notification(request, notif_id):
    """Marks a notification as read and redirects the user to the exact target."""
    try:
        notif = Notification.objects.get(id=notif_id, recipient=request.user)
        notif.is_read = True
        notif.save()
        
        if notif.target_url:
            return redirect(notif.target_url)
            
    except Notification.DoesNotExist:
        pass

    return redirect('dashboard')