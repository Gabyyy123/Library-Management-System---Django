from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from datetime import date, timedelta
from django.utils import timezone
from django.db.models import Count, Q
import json
from .models import Book, Category, BorrowRecord, UserProfile, Computer, MeetingRoomSchedule, EnrolledStudent
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.http import HttpResponse
from django.conf import settings  
from django.contrib.auth import update_session_auth_hash
from django.http import HttpResponse
import random
from django.urls import reverse

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
    profile = request.user.userprofile
    if request.method == 'POST':
        new_id = request.POST.get('id_number')
        new_email = request.POST.get('email') # Get the new email
        
        if new_id:
            profile.id_number = new_id
            request.user.username = new_id
            
        if new_email:
            profile.email = new_email # Save to profile
            request.user.email = new_email # Save to core user
            
        request.user.save()
            
        if 'profile_photo' in request.FILES: 
            profile.profile_photo = request.FILES['profile_photo']
            
        profile.save()
        return redirect(request.META.get('HTTP_REFERER', 'dashboard'))
        
    return render(request, 'catalog/edit_profile.html', {'profile': profile, 'active_tab': 'profile'})

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
            # Create account: Username AND Password are the exact 7-digit ID Number
            user = User.objects.create_user(
                username=student.id_number, 
                password=student.id_number, # No more "cec" prefix
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
            
    # Redirect back to the masterlist, staying on the same department tab
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
    
    departments = ['BSIT', 'BSCRIM', 'BSHM', 'BSTM', 'BSED Major in english', 'BSED Major in math', 'BEED']
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
def generate_sample_students(request):
    if request.user.userprofile.role != 'admin': return redirect('dashboard')
    
    # THE FIX: Grab the department from the URL so we know where to redirect back to
    current_dept = request.GET.get('department', 'BSIT')
    
    departments = ['BSIT', 'BSCRIM', 'BSHM', 'BSTM', 'BSED Major in english', 'BSED Major in math', 'BEED']
    first_names = ["John", "Jane", "Mark", "Maria", "Paul", "Anna", "David", "Sarah", "James", "Emily"]
    last_names = ["Doe", "Smith", "Garcia", "Reyes", "Cruz", "Bautista", "Ocampo", "Aquino", "Mendoza", "Santos"]

    base_id = 2310000
    
    # Generate 10 students for EVERY department (70 total)
    for d_idx, dept in enumerate(departments):
        for i in range(1, 11): # Loop 10 times
            student_id = str(base_id + (d_idx * 100) + i) # Ensures unique 7-digit ID
            
            # Randomize enrollment year (between 2022 and 2025) to test the dynamic Year Level
            random_enrollment = random.choice([2022, 2023, 2024, 2025])
            
            EnrolledStudent.objects.get_or_create(
                id_number=student_id, 
                defaults={
                    'first_name': random.choice(first_names), 
                    'last_name': random.choice(last_names), 
                    'department': dept,
                    'enrollment_year': random_enrollment
                }
            )
            
    # THE FIX: Redirect precisely back to the tab the admin was viewing
    base_url = reverse('admin_masterlist')
    return redirect(f"{base_url}?department={current_dept}")
