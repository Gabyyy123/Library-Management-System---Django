from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from datetime import date, timedelta
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
from django.http import HttpResponse
import random
from django.urls import reverse
import openpyxl
from django.contrib import messages

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
def admin_meetings(request):
    if request.user.userprofile.role != 'admin': return redirect('dashboard')
    context = {'profile': request.user.userprofile, 'active_tab': 'meetings', 'active_meetings': MeetingRoomSchedule.objects.filter(status='Upcoming').order_by('date')}
    return render(request, 'catalog/admin_meetings.html', context)

@login_required
def admin_history(request):
    if request.user.userprofile.role != 'admin': return redirect('dashboard')
    context = {'profile': request.user.userprofile, 'active_tab': 'history', 'history_borrows': BorrowRecord.objects.filter(is_returned=True).order_by('-return_date'), 'history_meetings': MeetingRoomSchedule.objects.filter(status='Completed').order_by('-date')}
    return render(request, 'catalog/admin_history.html', context)

@login_required
def admin_management(request):
    if request.user.userprofile.role != 'admin': return redirect('dashboard')
    
    # 1. Inventory Search Logic
    inventory_q = request.GET.get('inventory_q', '')
    books = Book.objects.all().order_by('book_id')
    if inventory_q: 
        books = books.filter(Q(title__icontains=inventory_q) | Q(book_id__icontains=inventory_q))

    # 2. Student Masterlist Search Logic
    student_q = request.GET.get('student_q', '')
    dept_filter = request.GET.get('department', '')
    sec_filter = request.GET.get('section', '')
    
    # Base query: get all students and instructors
    all_users = User.objects.filter(userprofile__role__in=['student', 'instructor']).order_by('username')
    
    # Apply search filter if admin typed a name or ID
    if student_q:
        all_users = all_users.filter(
            Q(username__icontains=student_q) | 
            Q(first_name__icontains=student_q) | 
            Q(last_name__icontains=student_q) | 
            Q(userprofile__id_number__icontains=student_q)
        )
        
    # [!] NOTE: If you eventually link Department and Section to your UserProfile model, 
    # you can uncomment the two lines below to make the dropdown filters work:
    # if dept_filter: all_users = all_users.filter(userprofile__department_id=dept_filter)
    # if sec_filter: all_users = all_users.filter(userprofile__section_id=sec_filter)

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
        # 1. Safely update Display Names (Does NOT touch the username)
        user.first_name = request.POST.get('first_name', user.first_name).strip()
        user.last_name = request.POST.get('last_name', user.last_name).strip()
        
        # 2. Safely update Email (Allows blank if they don't want to provide one)
        new_email = request.POST.get('email', '').strip()
        if new_email:
            user.email = new_email
        
        user.save()

        # 3. Update the custom Profile data (ID Number and Photo)
        profile.id_number = request.POST.get('id_number', profile.id_number).strip()
        
        if 'profile_photo' in request.FILES:
            profile.profile_photo = request.FILES['profile_photo']
            
        profile.save()
        
        # Add a success message here if you want!
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
                    # NEW: Changed to settings.EMAIL_HOST_USER
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
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))

@login_required
def approve_pc(request, pc_id):
    if request.user.userprofile.role == 'admin':
        pc = get_object_or_404(Computer, id=pc_id)
        if pc.status == 'Requested':
            pc.status = 'In Use'
            pc.time_started = timezone.now()
            pc.save()
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))

@login_required
def reject_pc(request, pc_id):
    if request.user.userprofile.role == 'admin':
        pc = get_object_or_404(Computer, id=pc_id)
        pc.status = 'Available'
        pc.current_user = None
        pc.save()
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))

@login_required
def stop_pc(request, pc_id):
    if request.user.userprofile.role == 'admin':
        pc = get_object_or_404(Computer, id=pc_id)
        pc.status = 'Available'
        pc.current_user = None
        pc.time_started = None
        pc.save()
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

# ==========================================
# NEW: AUTOMATED 1-DAY REMINDER SYSTEM
# ==========================================
def send_daily_reminders(request):
    """
    Finds all books due exactly tomorrow and sends an email.
    Notice there is no @login_required here, so our internet robot can access it.
    """
    tomorrow = date.today() + timedelta(days=1)
    
    # 1. Get records that are NOT returned and are due exactly tomorrow
    due_tomorrow_records = BorrowRecord.objects.filter(is_returned=False, due_date=tomorrow)
    
    emails_sent = 0
    for record in due_tomorrow_records:
        student_email = record.user.userprofile.email
        if student_email:
            subject = f"Library Reminder: '{record.book.title}' is due tomorrow!"
            message = f"""Hello {record.user.username},

This is an automated reminder from the Library System.

Your borrowed book '{record.book.title}' is due tomorrow ({tomorrow.strftime('%b %d, %Y')}).
Please return it on time to avoid a penalty fee of ₱5.00 per day.

Thank you!
CEC Library System"""
            
            try:
                # NEW: Changed to settings.EMAIL_HOST_USER
                send_mail(subject, message, settings.EMAIL_HOST_USER, [student_email], fail_silently=False)
                emails_sent += 1
            except Exception as e:
                print(f"Error sending to {student_email}: {e}")

    # This text will show up on the screen when the robot visits the link
    return HttpResponse(f"System Check Complete. Sent {emails_sent} reminder emails for books due on {tomorrow} using {settings.EMAIL_HOST_USER}.")


@login_required
def digital_id(request):
    profile = request.user.userprofile
    return render(request, 'catalog/digital_id.html', {'profile': profile, 'active_tab': 'digital_id'})

@login_required
def admin_user_logs(request):
    # Security check: Only let Admins in
    if request.user.userprofile.role != 'admin':
        return redirect('dashboard')
    
    query = request.GET.get('q', '')
    
    # Get all users who are NOT admins
    users = User.objects.exclude(userprofile__role='admin').order_by('username')
    
    # If admin typed in the search bar, filter the users
    if query:
        users = users.filter(
            Q(username__icontains=query) | 
            Q(first_name__icontains=query) | 
            Q(last_name__icontains=query) | 
            Q(userprofile__id_number__icontains=query)
        )
    
    # Bundle each user with their last borrowed book to send to the HTML
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
            # 1. Format the name into a valid username (e.g., "John Doe" -> "john.doe")
            base_username = f"{student.first_name.strip()}.{student.last_name.strip()}".replace(" ", "").lower()
            
            # 2. Check for duplicates (If there are two John Does, the second becomes john.doe1)
            username = base_username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1

            # 3. Create the account
            user = User.objects.create_user(
                username=username,           # Username is now their formatted name
                password=student.id_number,  # Password is their exact ID number
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
            # Update the password
            request.user.set_password(new_pass)
            request.user.save()
            # This keeps the user logged in after the password changes
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
        # THE FIX: Split "John Doe" into ["John", "Doe"] and search both
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
        
        # Update Masterlist record
        student.enrollment_status = new_status
        student.save()

        # Update Login Account access
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
            
            # Map headers to lowercase for easier finding
            headers = [str(cell.value).strip().lower() if cell.value else '' for cell in sheet[1]]
            
            id_idx = headers.index('id_number')
            fname_idx = headers.index('first_name')
            lname_idx = headers.index('last_name')
            dept_idx = headers.index('department')
            year_idx = headers.index('enrollment_year')
            
            officially_enrolled_ids = set()
            
            for row in sheet.iter_rows(min_row=2, values_only=True):
                # --- ID NUMBER CLEANER (Removes the .0) ---
                raw_id = row[id_idx]
                if isinstance(raw_id, float):
                    student_id = str(int(raw_id)) # Converts 2310102.0 to "2310102"
                else:
                    student_id = str(raw_id).strip() if raw_id else ''
                
                if not student_id or student_id == 'None': continue
                
                officially_enrolled_ids.add(student_id)
                
                # Clean other fields
                first_name = str(row[fname_idx]).strip() if row[fname_idx] else 'Unknown'
                last_name = str(row[lname_idx]).strip() if row[lname_idx] else 'Unknown'
                department = str(row[dept_idx]).strip() if row[dept_idx] else 'Unknown'
                
                try:
                    enroll_year = int(row[year_idx])
                except (ValueError, TypeError):
                    enroll_year = date.today().year
                
                # Create or Update
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
                    student.department = department # Updates dept if you changed it in Excel
                    student.enrollment_year = enroll_year
                    student.save()
                    
                # Auto-unlock account if active
                if student.is_activated:
                    try:
                        profile = UserProfile.objects.get(id_number=student.id_number)
                        profile.user.is_active = True
                        profile.user.save()
                    except UserProfile.DoesNotExist:
                        pass

            # Sweep: Mark missing students as Dropped
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
    
    # Get all meetings, putting the 'Pending' ones at the very top
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
        action = request.POST.get('action') # Will be 'Approve' or 'Reject'
        
        if action == 'Approve':
            # Double check for conflicts one last time just in case!
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
                
                # Pro-tip: Automatically reject other pending requests for this same time
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
            
    return redirect('admin_meetings')

@login_required
def student_meetings(request):
    if request.user.userprofile.role == 'admin': return redirect('admin_meetings')
        
    if request.method == 'POST':
        date = request.POST.get('meeting_date')
        start = request.POST.get('start_time')
        end = request.POST.get('end_time')
        purpose = request.POST.get('purpose')
        
        # 1. THE AUTO-REJECT LOGIC (Conflict Check)
        # Check if an 'Approved' meeting already exists on this date that overlaps with these times
        conflicts = Meeting.objects.filter(
            meeting_date=date,
            status='Approved',
            start_time__lt=end, # New meeting ends AFTER existing meeting starts
            end_time__gt=start  # New meeting starts BEFORE existing meeting ends
        )
        
        if conflicts.exists():
            # Time slot is taken! Tell the student.
            messages.error(request, "This time slot is already booked by someone else.")
        else:
            # Time slot is free! Save the pending request.
            Meeting.objects.create(
                student=request.user,
                meeting_date=date,
                start_time=start,
                end_time=end,
                purpose=purpose,
                status='Pending'
            )
            messages.success(request, "Meeting request submitted! Waiting for admin approval.")
            
        return redirect('student_meetings')

    # Fetch this specific student's appointments to show on the right side of the screen
    my_appointments = Meeting.objects.filter(student=request.user).order_by('-meeting_date', '-start_time')

    context = {
        'profile': request.user.userprofile,
        'active_tab': 'meetings',
        'appointments': my_appointments
    }
    return render(request, 'catalog/student_meetings.html', context)



@login_required
def secret_wipe_data(request):
    # SECURITY: Only you (the Superuser) can run this!
    if not request.user.is_superuser:
        return redirect('dashboard')
        
    # 1. Delete all records from the Masterlist
    EnrolledStudent.objects.all().delete()
    
    # 2. Delete all generated User accounts (EXCEPT your Admin/Superuser)
    User.objects.filter(is_superuser=False, is_staff=False).delete()
    
    # Send a success message
    messages.success(request, "SYSTEM WIPED: All test students and accounts have been deleted.")
    return redirect('admin_masterlist')