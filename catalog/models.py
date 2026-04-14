from django.db import models
from django.contrib.auth.models import User
from datetime import date
from cloudinary.models import CloudinaryField

from django.db import models
from django.contrib.auth.models import User
from cloudinary.models import CloudinaryField  # <-- CRITICAL NEW IMPORT

class UserProfile(models.Model):
    ROLE_CHOICES = (
        ('student', 'Student'), 
        ('instructor', 'Instructor'), 
        ('admin', 'Librarian')
    )
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='student')
    id_number = models.CharField(max_length=50, blank=True)
    email = models.EmailField(max_length=255, blank=True, null=True)
    profile_photo = CloudinaryField('image', blank=True, null=True)

    def __str__(self): 
        return self.user.username

class Category(models.Model):
    name = models.CharField(max_length=100)
    def __str__(self): return self.name

class Book(models.Model):
    # Added 'Unavailable' status for Librarian manual control
    STATUS_CHOICES = (('Available', 'Available'), ('Pending', 'Pending'), ('Borrowed', 'Borrowed'), ('Unavailable', 'Unavailable'))
    book_id = models.CharField(max_length=20, unique=True)
    title = models.CharField(max_length=255)
    author = models.CharField(max_length=255)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Available')

    def __str__(self): return f"[{self.book_id}] {self.title}"

class BorrowRecord(models.Model):
    book = models.ForeignKey(Book, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    borrow_date = models.DateField(auto_now_add=True)
    due_date = models.DateField()
    is_returned = models.BooleanField(default=False)
    return_date = models.DateField(null=True, blank=True)
    
    # NEW: Saves the final penalty to history permanently
    final_penalty = models.IntegerField(default=0)

    @property
    def penalty_fee(self):
        if self.is_returned: return self.final_penalty
        if self.book.status == 'Pending': return 0
        days_late = (date.today() - self.due_date).days
        return max(0, days_late * 5)

class Computer(models.Model):
    STATUS_CHOICES = (('Available', 'Available'), ('Requested', 'Requested'), ('In Use', 'In Use'))
    name = models.CharField(max_length=50)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Available')
    current_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    time_started = models.DateTimeField(null=True, blank=True)

class MeetingRoomSchedule(models.Model):
    STATUS_CHOICES = (('Upcoming', 'Upcoming'), ('Completed', 'Completed'))
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    date = models.DateField()
    time_slot = models.CharField(max_length=100)
    purpose = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Upcoming')

class EnrolledStudent(models.Model):
    # 1. 'Safe' Status Choices (Prevents deleting historical student records)
    STATUS_CHOICES = (
        ('Enrolled', 'Enrolled'),
        ('Dropped', 'Dropped'),
        ('Transferred', 'Transferred'),
        ('Graduated', 'Graduated')
    )

    id_number = models.CharField(max_length=50, unique=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    department = models.CharField(max_length=100, blank=True, null=True)
    section = models.CharField(max_length=50, blank=True, null=True)
    
    # Tracks when they started to calculate their year dynamically
    enrollment_year = models.IntegerField(default=date.today().year)
    
    is_activated = models.BooleanField(default=False) 
    
    # 2. NEW: Safely track their status instead of deleting them
    enrollment_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Enrolled')

    @property
    def current_year_level(self):
        """Calculates the student's year level based on current date"""
        current_year = date.today().year
        current_month = date.today().month
        
        # Assumes the new school year shifts in August
        academic_year = current_year if current_month >= 8 else current_year - 1
        
        year_diff = academic_year - self.enrollment_year + 1
        
        if year_diff == 1: return "1st Year"
        elif year_diff == 2: return "2nd Year"
        elif year_diff == 3: return "3rd Year"
        elif year_diff == 4: return "4th Year"
        elif year_diff > 4: return f"{year_diff}th Year"
        else: return "Incoming"

    @property
    def expected_username(self):
        """Calculates the exact username preview for the UI popup"""
        return f"{self.first_name.strip()}.{self.last_name.strip()}".replace(" ", "").lower()

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.id_number} - {self.department})"

class Meeting(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE)
    meeting_date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    purpose = models.TextField()
    
    # The status field is what makes the Accept/Reject logic work!
    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected')
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.student.username} - {self.meeting_date}"

class Notification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    message = models.CharField(max_length=255)
    is_read = models.BooleanField(default=False)
    target_url = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at'] 

    def __str__(self):
        return f"To {self.recipient.username}: {self.message}"