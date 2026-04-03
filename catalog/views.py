from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from datetime import date, timedelta
from django.utils import timezone
from django.db.models import Count, Q
import json
from .models import Book, Category, BorrowRecord, UserProfile, Computer, MeetingRoomSchedule
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.http import HttpResponse
from django.conf import settings  # NEW: Imports settings so we can use EMAIL_HOST_USER dynamically

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
    inventory_q = request.GET.get('inventory_q', '')
    books = Book.objects.all().order_by('book_id')
    if inventory_q: books = books.filter(title__icontains=inventory_q) | books.filter(book_id__icontains=inventory_q)
    context = {'profile': request.user.userprofile, 'active_tab': 'management', 'categories': Category.objects.all(), 'books': books, 'total_books': Book.objects.count(), 'available_books': Book.objects.filter(status='Available').count(), 'unavailable_books': Book.objects.exclude(status='Available').count(), 'inventory_q': inventory_q, 'all_users': User.objects.filter(userprofile__role__in=['student', 'instructor']).order_by('username')}
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
        profile.id_number = request.POST.get('id_number')
        if 'profile_photo' in request.FILES: profile.profile_photo = request.FILES['profile_photo']
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